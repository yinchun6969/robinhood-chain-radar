#!/usr/bin/env python3
import os
import json
import time
import sqlite3
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

APP = Path(__file__).resolve().parent
DB = os.getenv("DB_PATH", str(APP / "radar.db"))
HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("DASHBOARD_PORT", "8787"))
VERSION = "1.3.0"


def connect():
    d = sqlite3.connect(DB, timeout=3)
    d.row_factory = sqlite3.Row
    return d


def kv(d, k, default=None):
    try:
        r = d.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default
    except Exception:
        return default


def jint(d, k, default=0):
    try:
        return int(float(kv(d, k, default) or default))
    except Exception:
        return int(default)


def jfloat(d, k, default=0):
    try:
        return float(kv(d, k, default) or default)
    except Exception:
        return float(default)


def metric(d, key, default=0):
    try:
        r = d.execute("SELECT value FROM pipeline_metrics WHERE key=?", (key,)).fetchone()
        return float(r["value"]) if r else float(default)
    except Exception:
        return float(default)


def jloads(v, default):
    try:
        return json.loads(v or "")
    except Exception:
        return default


def _count(d, sql, args=()):
    try:
        return int(d.execute(sql, args).fetchone()[0])
    except Exception:
        return 0


def snapshot():
    d = connect()
    now = int(time.time())

    hb = jint(d, "fast_scanner_heartbeat", jint(d, "heartbeat", 0))
    last = jint(d, "fast_scanner_last_block", jint(d, "last_block", 0))
    head = jint(d, "fast_scanner_head", jint(d, "latest_head", last))

    fast_hbs = [jint(d, "worker_heartbeat_fast_1", 0), jint(d, "worker_heartbeat_fast_2", 0)]
    meta_hb = jint(d, "worker_heartbeat_meta_1", 0)
    fast_live = sum(1 for x in fast_hbs if x and now - x < 60)
    fast_rate = sum(jfloat(d, f"worker_rate_fast_{i}", 0) for i in (1, 2))
    meta_rate = jfloat(d, "worker_rate_meta_1", 0)

    target = jint(d, "swap_filter_target_workers", 3)
    swap_live = 0
    swap_rate = 0.0
    for i in (1, 2, 3):
        shb = jint(d, f"swap_filter_heartbeat_{i}", 0)
        active = jint(d, f"swap_filter_active_{i}", 0)
        if shb and now - shb < 60 and active:
            swap_live += 1
        swap_rate += jfloat(d, f"swap_filter_rate_{i}", 0)

    native_hb = jint(d, "native_scanner_heartbeat", 0)
    native_last = jint(d, "native_scanner_last_block", last)
    native_head = jint(d, "native_scanner_head", head)
    token_hb = jint(d, "token_radar_heartbeat", 0)

    fast_pending = _count(d, "SELECT COUNT(*) FROM raw_events WHERE status=0 AND priority>=100")
    fast_processing = _count(d, "SELECT COUNT(*) FROM raw_events WHERE status=1 AND priority>=100")
    fast_deferred = _count(d, "SELECT COUNT(*) FROM raw_events WHERE status=2 AND priority>=100")
    meta_pending = _count(d, "SELECT COUNT(*) FROM raw_events WHERE status=0 AND priority<100")
    meta_processing = _count(d, "SELECT COUNT(*) FROM raw_events WHERE status=1 AND priority<100")
    swap_pending = _count(d, "SELECT COUNT(*) FROM swap_events WHERE status=0")
    swap_processing = _count(d, "SELECT COUNT(*) FROM swap_events WHERE status=1")
    swap_deferred = _count(d, "SELECT COUNT(*) FROM swap_events WHERE status=2")
    resolver_pending = _count(d, "SELECT COUNT(*) FROM v4_resolve_queue WHERE status IN (0,1)")
    token_pending = _count(d, "SELECT COUNT(*) FROM token_scan_queue WHERE status IN (0,1)")
    token_urgent = _count(d, "SELECT COUNT(*) FROM token_scan_queue WHERE status IN (0,1) AND priority>=80")

    try:
        hot_wallets = []
        rows = d.execute('''SELECT address,last_seen_ts,first_tx_count,is_fresh,score,tags,
                                   bridge_usd_24h,lp_usd_24h,swap_usd_24h,event_count_24h
                            FROM address_profiles
                            WHERE event_count_24h>0 AND last_seen_ts>=?
                            ORDER BY score DESC,last_seen_ts DESC LIMIT 20''', (now - 86400,)).fetchall()
        for r in rows:
            hot_wallets.append({
                "address": r["address"], "last_seen_ts": r["last_seen_ts"],
                "first_tx_count": r["first_tx_count"], "is_fresh": bool(r["is_fresh"]),
                "score": r["score"], "tags": jloads(r["tags"], []),
                "bridge_usd_24h": r["bridge_usd_24h"], "lp_usd_24h": r["lp_usd_24h"],
                "swap_usd_24h": r["swap_usd_24h"], "event_count_24h": r["event_count_24h"],
            })
    except Exception:
        hot_wallets = []

    try:
        hot_tokens = []
        rows = d.execute('''SELECT token,symbol,first_seen_ts,last_seen_ts,event_count_24h,
                                   buy_usd_24h,sell_usd_24h,lp_add_usd_24h,lp_remove_usd_24h,
                                   bridge_usd_24h,unique_wallets_24h,hot_wallets_24h,pool_count_24h,
                                   lp_drain_ratio,capital_score,risk_score,signal_score,signal_level,tags,holders_json,risk_json,
                                   sequence_json,last_deep_scan_ts
                            FROM token_profiles
                            WHERE event_count_24h>0 AND last_seen_ts>=?
                            ORDER BY signal_score DESC,capital_score DESC,last_seen_ts DESC LIMIT 30''',
                         (now - 86400,)).fetchall()
        for r in rows:
            x = dict(r)
            x["tags"] = jloads(x.get("tags"), [])
            x["holders"] = jloads(x.pop("holders_json", None), {})
            x["risk"] = jloads(x.pop("risk_json", None), {})
            x["sequence"] = jloads(x.pop("sequence_json", None), {})
            x["net_buy_usd_24h"] = float(x.get("buy_usd_24h") or 0) - float(x.get("sell_usd_24h") or 0)
            x["lp_net_usd_24h"] = float(x.get("lp_add_usd_24h") or 0) - float(x.get("lp_remove_usd_24h") or 0)
            hot_tokens.append(x)
    except Exception:
        hot_tokens = []

    try:
        timeline = []
        rows = d.execute('''SELECT id,ts,address,event_type,protocol,action,usd,token_pair,
                                   subject,tx_hash,block_number,metadata
                            FROM address_events ORDER BY id DESC LIMIT 80''').fetchall()
        for r in rows:
            x = dict(r)
            x["metadata"] = jloads(x.get("metadata"), {})
            timeline.append(x)
    except Exception:
        timeline = []

    supervisor_hb = jint(d, "supervisor_heartbeat", 0)
    supervisor_started = jint(d, "supervisor_started_at", 0)

    out = {
        "version": VERSION,
        "supervisor_running": bool(supervisor_hb and now - supervisor_hb < 30),
        "supervisor_uptime": max(0, now - supervisor_started) if supervisor_started else 0,
        "supervisor_restarts": jint(d, "supervisor_component_restarts", 0),
        "supervisor_self_restarts": jint(d, "supervisor_self_restarts", 0),
        "rss_mb": round(jfloat(d, "supervisor_rss_mb", 0), 1),
        "threads_live": jint(d, "supervisor_threads_live", 0),
        "threads_expected": jint(d, "supervisor_threads_expected", 0),
        "db_mb": round(jfloat(d, "maintenance_db_mb", 0), 1),
        "expired_swap": int(metric(d, "swap_expired")),
        "expired_fast": int(metric(d, "fast_expired")),
        "running": bool(hb and now - hb < 30),
        "heartbeat_age": now - hb if hb else None,
        "last_block": last, "head": head, "lag": max(0, head - last),
        "scanner_rpc_ms": jint(d, "fast_scanner_rpc_ms", 0),
        "scanner_batch_ms": jint(d, "fast_scanner_batch_ms", 0),
        "fast_pending": fast_pending, "fast_processing": fast_processing,
        "fast_deferred": fast_deferred, "fast_workers": fast_live,
        "fast_rate": round(fast_rate, 2),
        "meta_pending": meta_pending, "meta_processing": meta_processing,
        "meta_live": bool(meta_hb and now - meta_hb < 60), "meta_rate": round(meta_rate, 2),
        "resolver_pending": resolver_pending,
        "swap_target": target, "swap_live": swap_live, "swap_rate": round(swap_rate, 2),
        "swap_pending": swap_pending, "swap_processing": swap_processing, "swap_deferred": swap_deferred,
        "swap_candidates": int(metric(d, "swap_candidates")),
        "swap_confirmed": int(metric(d, "swap_confirmed")),
        "swap_small": int(metric(d, "swap_small")),
        "swap_unanchored": int(metric(d, "swap_unanchored")),
        "swap_wrong_pool": int(metric(d, "swap_wrong_pool")),
        "swap_no_input": int(metric(d, "swap_no_input")),
        "swap_zero_reserve": int(metric(d, "swap_zero_reserve")),
        "swap_other_unpriced": int(metric(d, "swap_other_unpriced")),
        "swap_errors": int(metric(d, "swap_errors")),
        "shadow_checked": int(metric(d, "swap_shadow_checked")),
        "shadow_missed": int(metric(d, "swap_shadow_missed")),
        "rpc_backoffs": int(metric(d, "swap_rpc_backoffs")),
        "native_running": bool(native_hb and now - native_hb < 60),
        "native_lag": max(0, native_head - native_last),
        "native_chunk": jint(d, "native_scanner_chunk", 0),
        "token_radar_running": bool(token_hb and now - token_hb < 60),
        "token_radar_age": now - token_hb if token_hb else None,
        "token_pending": token_pending,
        "token_urgent": token_urgent,
        "alerts24": _count(d, "SELECT COUNT(*) FROM alerts WHERE ts>=?", (now - 86400,)),
        "p0_24": _count(d, "SELECT COUNT(*) FROM alerts WHERE ts>=? AND severity='P0'", (now - 86400,)),
        "token_signal24": _count(d, "SELECT COUNT(*) FROM token_signals WHERE ts>=?", (now - 86400,)),
        "token_p0_24": _count(d, "SELECT COUNT(*) FROM token_signals WHERE ts>=? AND level='P0'", (now - 86400,)),
        "token_p1_24": _count(d, "SELECT COUNT(*) FROM token_signals WHERE ts>=? AND level='P1'", (now - 86400,)),
        "wallets24": _count(d, "SELECT COUNT(*) FROM address_profiles WHERE event_count_24h>0 AND last_seen_ts>=?", (now - 86400,)),
        "tokens24": _count(d, "SELECT COUNT(*) FROM token_profiles WHERE event_count_24h>0 AND last_seen_ts>=?", (now - 86400,)),
        "hot_wallets": hot_wallets,
        "hot_tokens": hot_tokens,
        "timeline": timeline,
    }
    d.close()
    return out


def address_detail(addr):
    d = connect()
    a = (addr or "").lower()
    try:
        p = d.execute("SELECT * FROM address_profiles WHERE address=?", (a,)).fetchone()
        events = d.execute("SELECT * FROM address_events WHERE address=? ORDER BY id DESC LIMIT 150", (a,)).fetchall()
        out = {"profile": dict(p) if p else None, "events": []}
        if out["profile"]:
            out["profile"]["tags"] = jloads(out["profile"].get("tags"), [])
        for r in events:
            x = dict(r); x["metadata"] = jloads(x.get("metadata"), {}); out["events"].append(x)
        return out
    finally:
        d.close()


def token_detail(token):
    d = connect()
    t = (token or "").lower()
    try:
        p = d.execute("SELECT * FROM token_profiles WHERE token=?", (t,)).fetchone()
        events = d.execute("SELECT * FROM token_events WHERE token=? ORDER BY id DESC LIMIT 150", (t,)).fetchall()
        signals = d.execute("SELECT * FROM token_signals WHERE token=? ORDER BY ts DESC LIMIT 30", (t,)).fetchall()
        out = {"profile": dict(p) if p else None, "events": [], "signals": []}
        if out["profile"]:
            for k in ("tags", "holders_json", "risk_json", "sequence_json"):
                if k in out["profile"]:
                    value = out["profile"].pop(k)
                    target = {"holders_json": "holders", "risk_json": "risk", "sequence_json": "sequence"}.get(k, k)
                    out["profile"][target] = jloads(value, [] if k == "tags" else {})
        for r in events:
            x = dict(r); x["metadata"] = jloads(x.get("metadata"), {}); out["events"].append(x)
        for r in signals:
            x = dict(r); x["details"] = jloads(x.get("details"), {}); out["signals"].append(x)
        return out
    finally:
        d.close()


LANG = {
    "zh": {
        "title": "Robinhood 链资金雷达", "sub": "V1.3.0 Token 早期资金雷达 · 主网 4663 · 仅本机访问",
        "langlink": "English", "langpath": "/en", "connecting": "连接中",
        "supervisor": "系统守护", "uptime": "运行时长", "scanner": "实时扫链", "lag": "区块延迟",
        "tokenradar": "Token 雷达", "tokens": "监控代币", "tokensignals": "Token 信号", "hotwallets": "热点地址",
        "fastq": "跨链 / LP 队列", "swap": "Swap 过滤器", "swapq": "Swap 积压", "native": "原生 ETH 延迟",
        "rpc": "扫链 RPC", "alerts": "总警报", "tabtokens": "Token 资金雷达", "tabwallets": "热点地址",
        "tabtimeline": "资金时间线", "tabpipeline": "运行管线", "tokensection": "Token 早期资金信号",
        "walletsection": "资金地址画像", "timelinesection": "全链大额资金行为时间线", "pipeline": "V1.3.0 实时监控管线",
        "no_tokens": "暂时没有达到 Token 雷达门槛的代币", "no_wallets": "暂时没有达到画像门槛的地址",
        "no_timeline": "暂时没有 ≥ $100K 行为事件", "detail": "本地详情", "score": "信号分", "risk": "风险",
        "capital": "资金", "buy": "买入", "sell": "卖出", "net": "净流", "lp": "LP 净流", "wallets": "地址",
        "holders": "持有人", "last": "最后活跃", "events": "事件", "running": "正常", "stale": "异常",
    },
    "en": {
        "title": "Robinhood Chain Radar", "sub": "V1.3.0 Token Early-Capital Radar · Mainnet 4663 · localhost only",
        "langlink": "中文", "langpath": "/zh", "connecting": "Connecting",
        "supervisor": "Supervisor", "uptime": "Uptime", "scanner": "Fast Scanner", "lag": "Block Lag",
        "tokenradar": "Token Radar", "tokens": "Tracked Tokens", "tokensignals": "Token Signals", "hotwallets": "Hot Wallets",
        "fastq": "Bridge / LP Queue", "swap": "Swap Filters", "swapq": "Swap Backlog", "native": "Native ETH Lag",
        "rpc": "Scanner RPC", "alerts": "Alerts", "tabtokens": "Token Radar", "tabwallets": "Hot Wallets",
        "tabtimeline": "Capital Timeline", "tabpipeline": "Pipeline", "tokensection": "Token Early-Capital Signals",
        "walletsection": "Capital Wallet Profiles", "timelinesection": "Large On-chain Capital Timeline", "pipeline": "V1.3.0 Realtime Pipeline",
        "no_tokens": "No tokens have reached the radar threshold yet", "no_wallets": "No wallets have reached the profile threshold yet",
        "no_timeline": "No ≥ $100K events yet", "detail": "Local detail", "score": "Signal", "risk": "Risk",
        "capital": "Capital", "buy": "Buy", "sell": "Sell", "net": "Net", "lp": "LP net", "wallets": "Wallets",
        "holders": "Holders", "last": "last", "events": "events", "running": "LIVE", "stale": "STALE",
    },
}

TEMPLATE = r'''<!doctype html><html lang="{{HTMLLANG}}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{{TITLE}} V1.3.0</title>
<style>
:root{color-scheme:dark;--bg:#06090e;--card:#0e1621;--card2:#111c2a;--line:#203044;--muted:#8292a8;--good:#27da82;--hot:#ff5b67;--warn:#ffb84d;--blue:#59b5ff;--cyan:#39e2d0;--violet:#ad8cff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% -10%,#0d2530 0,transparent 30%),var(--bg);color:#f5f7fb;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:auto;padding:18px 13px 44px}.head{display:flex;justify-content:space-between;align-items:center;gap:12px}.title{font-size:22px;font-weight:850}.title b{color:var(--cyan)}.sub{font-size:11px;color:var(--muted);margin-top:4px}.badge,.tag,.tab{border:1px solid var(--line);border-radius:999px}.badge{padding:7px 11px;font-size:11px}.on{color:var(--good)}.off{color:var(--hot)}.warn{color:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;margin-top:14px}.card,.item,.event,.empty{background:linear-gradient(180deg,var(--card2),var(--card));border:1px solid var(--line);border-radius:14px}.card{padding:12px}.k{font-size:10px;letter-spacing:.07em;color:var(--muted);text-transform:uppercase}.v{font-size:22px;font-weight:850;margin-top:3px}.sm{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.45}
.tabs{display:flex;gap:7px;overflow:auto;margin:16px 0 10px}.tab{padding:8px 12px;white-space:nowrap;font-size:12px;background:transparent;color:#c9d2df}.tab.active{background:#16263a;color:#fff;border-color:#31506e}.panel{display:none}.panel.active{display:block}.section-title{font-size:14px;font-weight:800;margin:13px 2px 8px}.item{padding:12px;margin-bottom:8px}.row{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.addr{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;color:var(--blue);overflow-wrap:anywhere}.symbol{font-size:16px;font-weight:850}.score{font-size:22px;font-weight:900}.score.p0{color:var(--hot)}.score.p1{color:var(--warn)}.score.p2{color:var(--cyan)}
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}.tag{font-size:10px;padding:4px 7px;color:#c8d2df}.tag.hot{color:var(--hot);border-color:#6b3035}.moneyline{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.65}.riskbar{height:5px;background:#1c2836;border-radius:8px;margin-top:8px;overflow:hidden}.riskbar i{display:block;height:100%;background:linear-gradient(90deg,var(--good),var(--warn),var(--hot))}
.event{padding:11px;margin-bottom:7px;border-left:3px solid var(--line)}.event.bridge{border-left-color:var(--violet)}.event.liquidity{border-left-color:var(--warn)}.event.swap{border-left-color:var(--blue)}.etype{font-size:12px;font-weight:800}.money{font-weight:850;color:var(--warn)}.meta{font-size:10.5px;color:var(--muted);line-height:1.55;margin-top:5px;overflow-wrap:anywhere}
a{color:var(--blue);text-decoration:none}.empty{text-align:center;padding:28px;color:var(--muted)}footer{font-size:10px;color:var(--muted);text-align:center;margin-top:20px}
@media(min-width:760px){.grid{grid-template-columns:repeat(6,1fr)}}
</style></head><body><main>
<div class="head"><div><div class="title">{{TITLE}} <b>V1.3.0</b></div><div class="sub">{{SUB}} · <a href="{{LANGPATH}}">{{LANGLINK}}</a></div></div><div id="status" class="badge">{{CONNECTING}}</div></div>
<div class="grid">
<div class="card"><div class="k">{{SUPERVISOR}}</div><div id="supervisor" class="v">—</div><div id="supervisorSub" class="sm">watchdog</div></div>
<div class="card"><div class="k">{{UPTIME}}</div><div id="uptime" class="v">—</div><div id="memory" class="sm">RSS</div></div>
<div class="card"><div class="k">{{SCANNER}}</div><div id="scanner" class="v">—</div><div id="hb" class="sm">heartbeat</div></div>
<div class="card"><div class="k">{{LAG}}</div><div id="lagv" class="v">—</div><div id="block" class="sm">block</div></div>
<div class="card"><div class="k">{{TOKENRADAR}}</div><div id="tokenRadar" class="v">—</div><div id="tokenRadarSub" class="sm">background intel</div></div>
<div class="card"><div class="k">{{TOKENS}}</div><div id="tokens" class="v">0</div><div class="sm">24h</div></div>
<div class="card"><div class="k">{{TOKENSIGNALS}}</div><div id="tokenSignals" class="v">0</div><div id="tokenSignalsSub" class="sm">P0 / P1</div></div>
<div class="card"><div class="k">{{HOTWALLETS}}</div><div id="wallets" class="v">0</div><div class="sm">24h</div></div>
<div class="card"><div class="k">{{FASTQ}}</div><div id="fastQ" class="v">0</div><div id="fastSub" class="sm">priority</div></div>
<div class="card"><div class="k">{{SWAP}}</div><div id="swapFilters" class="v">—</div><div id="swapRate" class="sm">adaptive</div></div>
<div class="card"><div class="k">{{SWAPQ}}</div><div id="swapQ" class="v">0</div><div id="swapQSub" class="sm">pending</div></div>
<div class="card"><div class="k">{{NATIVE}}</div><div id="nativeLag" class="v">—</div><div id="nativeSub" class="sm">ETH</div></div>
<div class="card"><div class="k">{{RPC}}</div><div id="rpc" class="v">—</div><div id="rpcSub" class="sm">latency</div></div>
<div class="card"><div class="k">{{ALERTS}}</div><div id="alerts" class="v">0</div><div id="p0" class="sm">P0 0</div></div>
</div>
<div class="tabs"><button class="tab active" data-p="tokensPanel">{{TABTOKENS}}</button><button class="tab" data-p="walletsPanel">{{TABWALLETS}}</button><button class="tab" data-p="timelinePanel">{{TABTIMELINE}}</button><button class="tab" data-p="pipelinePanel">{{TABPIPELINE}}</button></div>
<section id="tokensPanel" class="panel active"><div class="section-title">{{TOKENSECTION}}</div><div id="tokenList"></div><div id="tokenDetail"></div></section>
<section id="walletsPanel" class="panel"><div class="section-title">{{WALLETSECTION}}</div><div id="hotlist"></div><div id="addressDetail"></div></section>
<section id="timelinePanel" class="panel"><div class="section-title">{{TIMELINESECTION}}</div><div id="timelineList"></div></section>
<section id="pipelinePanel" class="panel"><div class="section-title">{{PIPELINE}}</div><div class="card"><div class="moneyline" id="pipelineText">...</div></div></section>
<footer>V1.3.0 · Token Early-Capital Radar · 3s refresh · SQLite WAL · 127.0.0.1 only</footer>
</main><script>
const X='https://robinhoodchain.blockscout.com', $=id=>document.getElementById(id), ZH={{ISZH}};
const L={{JSLANG}};
function money(v){if(v==null)return '—';let n=Number(v),sign=n<0?'-':'';n=Math.abs(n);if(n>=1e6)return sign+'$'+(n/1e6).toFixed(2)+'M';if(n>=1e3)return sign+'$'+(n/1e3).toFixed(1)+'K';return sign+'$'+n.toLocaleString(undefined,{maximumFractionDigits:0})}
function pct(v){return v==null?'—':Number(v).toFixed(1)+'%'} function short(a){return a?(a.slice(0,8)+'…'+a.slice(-6)):'—'}
function ago(ts){let s=Math.max(0,Math.floor(Date.now()/1000-Number(ts||0)));if(s<60)return s+(ZH?'秒':'s');if(s<3600)return Math.floor(s/60)+(ZH?'分钟':'m');if(s<86400)return Math.floor(s/3600)+(ZH?'小时':'h');return Math.floor(s/86400)+(ZH?'天':'d')}
function duration(s){s=Number(s||0);if(s<3600)return Math.floor(s/60)+(ZH?'分钟':'m');if(s<86400)return Math.floor(s/3600)+(ZH?'小时':'h')+' '+Math.floor((s%3600)/60)+(ZH?'分钟':'m');return Math.floor(s/86400)+(ZH?'天':'d')+' '+Math.floor((s%86400)/3600)+(ZH?'小时':'h')}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab,.panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(b.dataset.p).classList.add('active')});
function tokenHTML(t){let lv=t.signal_level||'WATCH',cls=lv==='P0'?'p0':lv==='P1'?'p1':'p2',h=t.holders||{};return `<div class="item"><div class="row"><div><div class="symbol">${t.symbol||'TOKEN'} · ${lv}</div><a class="addr" href="${X}/address/${t.token}" target="_blank">${t.token}</a><div class="tags">${(t.tags||[]).map(x=>`<span class="tag ${x==='HIGH RISK'?'hot':''}">${x}</span>`).join('')}</div></div><div class="score ${cls}">${t.signal_score||0}</div></div><div class="moneyline">${L.capital} ${t.capital_score||0}/100 · ${L.risk} ${t.risk_score||0}/100<br>${L.buy} ${money(t.buy_usd_24h)} · ${L.sell} ${money(t.sell_usd_24h)} · ${L.net} ${money(t.net_buy_usd_24h)}<br>${L.lp} ${money(t.lp_net_usd_24h)} · pools ${t.pool_count_24h||0} · ${L.wallets} ${t.unique_wallets_24h||0} · ${L.holders} ${h.holders??'—'} · Top1 ${pct(h.top1)} · Top10 ${pct(h.top10)}<br>${L.last} ${ago(t.last_seen_ts)} · <a href="#" onclick="openToken('${t.token}');return false">${L.detail} ↓</a></div><div class="riskbar"><i style="width:${Math.min(100,t.risk_score||0)}%"></i></div></div>`}
function walletHTML(w){let sc=w.score||0,cls=sc>=80?'p0':sc>=50?'p1':'p2';return `<div class="item"><div class="row"><div><a class="addr" href="${X}/address/${w.address}" target="_blank">${w.address}</a><div class="tags">${(w.tags||[]).map(t=>`<span class="tag">${t}</span>`).join('')}</div></div><div class="score ${cls}">${sc}</div></div><div class="moneyline">Bridge ${money(w.bridge_usd_24h)} · LP ${money(w.lp_usd_24h)} · Swap ${money(w.swap_usd_24h)}<br>${w.event_count_24h} ${L.events} · ${L.last} ${ago(w.last_seen_ts)} · <a href="#" onclick="openAddress('${w.address}');return false">${L.detail} ↓</a></div></div>`}
function eventHTML(e){return `<div class="event ${e.event_type}"><div class="row"><div class="etype">${e.protocol} · ${e.action}</div><div class="money">${money(e.usd)}</div></div><div class="meta"><a href="${X}/address/${e.address||e.actor||e.subject}" target="_blank">${short(e.address||e.actor||e.subject)}</a>${e.token_pair?' · '+e.token_pair:''}<br>Block ${e.block_number||'—'} · ${ago(e.ts)}${e.tx_hash?` · <a href="${X}/tx/${e.tx_hash}" target="_blank">Tx ↗</a>`:''}</div></div>`}
async function openAddress(a){try{const d=await fetch('/api/address?address='+encodeURIComponent(a),{cache:'no-store'}).then(r=>r.json());const p=d.profile||{};$('addressDetail').innerHTML=`<div class="section-title">${short(a)} · ${L.score} ${p.score??'—'}</div>`+(d.events?.length?d.events.map(eventHTML).join(''):'<div class="empty">—</div>');$('addressDetail').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){}}
async function openToken(t){try{const d=await fetch('/api/token?token='+encodeURIComponent(t),{cache:'no-store'}).then(r=>r.json());const p=d.profile||{};$('tokenDetail').innerHTML=`<div class="section-title">${p.symbol||'TOKEN'} · ${short(t)} · ${L.score} ${p.signal_score??'—'} · ${L.risk} ${p.risk_score??'—'}</div>`+(d.events?.length?d.events.map(eventHTML).join(''):'<div class="empty">—</div>');$('tokenDetail').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){}}
async function refresh(){try{const d=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());
$('supervisor').textContent=d.supervisor_running?L.running:L.stale;$('supervisor').className='v '+(d.supervisor_running?'':'warn');$('supervisorSub').textContent=`threads ${d.threads_live}/${d.threads_expected} · restarts ${d.supervisor_restarts}/${d.supervisor_self_restarts}`;
$('uptime').textContent=duration(d.supervisor_uptime);$('memory').textContent=`RSS ${d.rss_mb} MB · DB ${d.db_mb} MB`;
$('status').textContent=d.running?'● '+L.running:'● '+L.stale;$('status').className='badge '+(d.running?'on':'off');$('scanner').textContent=d.running?L.running:L.stale;$('hb').textContent=(d.heartbeat_age??'—')+'s';
$('lagv').textContent=d.lag;$('block').textContent='block '+Number(d.last_block||0).toLocaleString();
$('tokenRadar').textContent=d.token_radar_running?L.running:L.stale;$('tokenRadar').className='v '+(d.token_radar_running?'':'warn');$('tokenRadarSub').textContent=`queue ${d.token_pending} · urgent ${d.token_urgent||0} · age ${d.token_radar_age??'—'}s`;
$('tokens').textContent=d.tokens24;$('tokenSignals').textContent=d.token_signal24;$('tokenSignalsSub').textContent=`P0 ${d.token_p0_24} · P1 ${d.token_p1_24}`;$('wallets').textContent=d.wallets24;
$('fastQ').textContent=d.fast_pending;$('fastSub').textContent=`processing ${d.fast_processing} · deferred ${d.fast_deferred} · ${d.fast_workers}/2 · ${Number(d.fast_rate).toFixed(1)}/s`;
$('swapFilters').textContent=d.swap_live+'/'+d.swap_target;$('swapRate').textContent=Number(d.swap_rate).toFixed(1)+'/s';$('swapQ').textContent=d.swap_pending;$('swapQSub').textContent=`processing ${d.swap_processing} · deferred ${d.swap_deferred}`;
$('nativeLag').textContent=d.native_lag;$('nativeSub').textContent=`${d.native_running?L.running:L.stale} · chunk ${d.native_chunk}`;$('rpc').textContent=d.scanner_rpc_ms+' ms';$('rpcSub').textContent=`getLogs ${d.scanner_batch_ms} ms · backoff ${d.rpc_backoffs}`;
$('alerts').textContent=d.alerts24;$('p0').textContent='P0 '+d.p0_24;
$('tokenList').innerHTML=d.hot_tokens?.length?d.hot_tokens.map(tokenHTML).join(''):`<div class="empty">{{NO_TOKENS}}</div>`;$('hotlist').innerHTML=d.hot_wallets?.length?d.hot_wallets.map(walletHTML).join(''):`<div class="empty">{{NO_WALLETS}}</div>`;$('timelineList').innerHTML=d.timeline?.length?d.timeline.map(eventHTML).join(''):`<div class="empty">{{NO_TIMELINE}}</div>`;
$('pipelineText').innerHTML=`<b>V1.3 Token Radar:</b> queue ${d.token_pending} · signals 24h ${d.token_signal24} · P0 ${d.token_p0_24} · P1 ${d.token_p1_24}<br><b>Priority lane:</b> ${d.fast_pending} pending · ${d.fast_workers}/2 workers · ${Number(d.fast_rate).toFixed(1)}/s<br><b>Swap lane:</b> ${d.swap_live}/${d.swap_target} workers · ${Number(d.swap_rate).toFixed(1)}/s · backlog ${d.swap_pending}<br><b>V4 resolver:</b> ${d.resolver_pending} pending · <b>Native ETH lag:</b> ${d.native_lag}<br><b>Freshness:</b> expired swaps ${d.expired_swap} · expired LP ${d.expired_fast}`;
}catch(e){$('status').textContent='● DASHBOARD ERROR';$('status').className='badge off'}}refresh();setInterval(refresh,3000);
</script></body></html>'''


def html_page(lang="zh"):
    lang = "zh" if lang == "zh" else "en"
    l = LANG[lang]
    repl = {
        "HTMLLANG": "zh-CN" if lang == "zh" else "en", "TITLE": l["title"], "SUB": l["sub"],
        "LANGPATH": l["langpath"], "LANGLINK": l["langlink"], "CONNECTING": l["connecting"],
        "SUPERVISOR": l["supervisor"], "UPTIME": l["uptime"], "SCANNER": l["scanner"], "LAG": l["lag"],
        "TOKENRADAR": l["tokenradar"], "TOKENS": l["tokens"], "TOKENSIGNALS": l["tokensignals"],
        "HOTWALLETS": l["hotwallets"], "FASTQ": l["fastq"], "SWAP": l["swap"], "SWAPQ": l["swapq"],
        "NATIVE": l["native"], "RPC": l["rpc"], "ALERTS": l["alerts"], "TABTOKENS": l["tabtokens"],
        "TABWALLETS": l["tabwallets"], "TABTIMELINE": l["tabtimeline"], "TABPIPELINE": l["tabpipeline"],
        "TOKENSECTION": l["tokensection"], "WALLETSECTION": l["walletsection"],
        "TIMELINESECTION": l["timelinesection"], "PIPELINE": l["pipeline"], "NO_TOKENS": l["no_tokens"],
        "NO_WALLETS": l["no_wallets"], "NO_TIMELINE": l["no_timeline"], "ISZH": "true" if lang == "zh" else "false",
        "JSLANG": json.dumps({k: l[k] for k in ("detail", "score", "risk", "capital", "buy", "sell", "net", "lp", "wallets", "holders", "last", "events", "running", "stale")}, ensure_ascii=False),
    }
    out = TEMPLATE
    for k, v in repl.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def health():
    s = snapshot()
    ok = bool(s.get("running") and s.get("token_radar_running") and s.get("supervisor_running"))
    return {
        "ok": ok,
        "version": s.get("version"),
        "scanner_live": bool(s.get("running")),
        "token_radar_live": bool(s.get("token_radar_running")),
        "supervisor_live": bool(s.get("supervisor_running")),
        "block_lag": int(s.get("lag") or 0),
        "token_queue": int(s.get("token_pending") or 0),
        "token_urgent": int(s.get("token_urgent") or 0),
        "rss_mb": float(s.get("rss_mb") or 0),
    }


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def sendb(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/health":
                h = health()
                self.sendb(200 if h.get("ok") else 503, "application/json; charset=utf-8", json.dumps(h, ensure_ascii=False).encode())
            elif u.path == "/api/status":
                self.sendb(200, "application/json; charset=utf-8", json.dumps(snapshot(), ensure_ascii=False).encode())
            elif u.path == "/api/address":
                a = (parse_qs(u.query).get("address") or [""])[0]
                self.sendb(200, "application/json; charset=utf-8", json.dumps(address_detail(a), ensure_ascii=False).encode())
            elif u.path == "/api/token":
                t = (parse_qs(u.query).get("token") or [""])[0]
                self.sendb(200, "application/json; charset=utf-8", json.dumps(token_detail(t), ensure_ascii=False).encode())
            elif u.path in ("/", "/zh"):
                self.sendb(200, "text/html; charset=utf-8", html_page("zh").encode())
            elif u.path == "/en":
                self.sendb(200, "text/html; charset=utf-8", html_page("en").encode())
            else:
                self.sendb(404, "text/plain; charset=utf-8", b"404")
        except Exception as e:
            self.sendb(500, "application/json; charset=utf-8", json.dumps({"error": str(e)}).encode())


def run_server():
    server = ThreadingHTTPServer((HOST, PORT), H)
    print(f"Dashboard V{VERSION}: http://{HOST}:{PORT}/zh | /en", flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    run_server()

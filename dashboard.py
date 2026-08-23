#!/usr/bin/env python3
import os, json, time, sqlite3
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

APP = Path(__file__).resolve().parent
DB = os.getenv("DB_PATH", str(APP / "radar.db"))
HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("DASHBOARD_PORT", "8787"))

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
        return int(float(kv(d,k,default) or default))
    except Exception:
        return int(default)

def jfloat(d, k, default=0):
    try:
        return float(kv(d,k,default) or default)
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

def snapshot():
    d = connect()
    now = int(time.time())

    hb = jint(d,"fast_scanner_heartbeat",jint(d,"heartbeat",0))
    last = jint(d,"fast_scanner_last_block",jint(d,"last_block",0))
    head = jint(d,"fast_scanner_head",jint(d,"latest_head",last))

    fast_hbs = [jint(d,"worker_heartbeat_fast_1",0), jint(d,"worker_heartbeat_fast_2",0)]
    meta_hb = jint(d,"worker_heartbeat_meta_1",0)
    fast_live = sum(1 for x in fast_hbs if x and now-x < 60)
    fast_rate = sum(jfloat(d,f"worker_rate_fast_{i}",0) for i in (1,2))
    meta_rate = jfloat(d,"worker_rate_meta_1",0)

    target = jint(d,"swap_filter_target_workers",3)
    swap_live = 0
    swap_rate = 0.0
    for i in (1,2,3):
        shb = jint(d,f"swap_filter_heartbeat_{i}",0)
        active = jint(d,f"swap_filter_active_{i}",0)
        if shb and now-shb < 60 and active:
            swap_live += 1
        swap_rate += jfloat(d,f"swap_filter_rate_{i}",0)

    native_hb = jint(d,"native_scanner_heartbeat",0)
    native_last = jint(d,"native_scanner_last_block",last)
    native_head = jint(d,"native_scanner_head",head)

    try:
        fast_pending = d.execute(
            "SELECT COUNT(*) n FROM raw_events WHERE status=0 AND priority>=100"
        ).fetchone()["n"]
        fast_processing = d.execute(
            "SELECT COUNT(*) n FROM raw_events WHERE status=1 AND priority>=100"
        ).fetchone()["n"]
        fast_deferred = d.execute(
            "SELECT COUNT(*) n FROM raw_events WHERE status=2 AND priority>=100"
        ).fetchone()["n"]

        meta_pending = d.execute(
            "SELECT COUNT(*) n FROM raw_events WHERE status=0 AND priority<100"
        ).fetchone()["n"]
        meta_processing = d.execute(
            "SELECT COUNT(*) n FROM raw_events WHERE status=1 AND priority<100"
        ).fetchone()["n"]

        swap_pending = d.execute(
            "SELECT COUNT(*) n FROM swap_events WHERE status=0"
        ).fetchone()["n"]
        swap_processing = d.execute(
            "SELECT COUNT(*) n FROM swap_events WHERE status=1"
        ).fetchone()["n"]
        swap_deferred = d.execute(
            "SELECT COUNT(*) n FROM swap_events WHERE status=2"
        ).fetchone()["n"]

        resolver_pending = d.execute(
            "SELECT COUNT(*) n FROM v4_resolve_queue WHERE status IN (0,1)"
        ).fetchone()["n"]
    except Exception:
        fast_pending=fast_processing=fast_deferred=0
        meta_pending=meta_processing=0
        swap_pending=swap_processing=swap_deferred=0
        resolver_pending=0

    def count_alerts(where="", args=()):
        try:
            return d.execute(
                "SELECT COUNT(*) n FROM alerts WHERE ts>=? "+where,
                (now-86400,*args)
            ).fetchone()["n"]
        except Exception:
            return 0

    try:
        hot=[]
        rows=d.execute('''SELECT address,last_seen_ts,first_tx_count,is_fresh,score,tags,
                                 bridge_usd_24h,lp_usd_24h,swap_usd_24h,event_count_24h
                          FROM address_profiles
                          WHERE event_count_24h>0 AND last_seen_ts>=?
                          ORDER BY score DESC,last_seen_ts DESC LIMIT 20''',
                       (now-86400,)).fetchall()
        for r in rows:
            hot.append({
                "address":r["address"],"last_seen_ts":r["last_seen_ts"],
                "first_tx_count":r["first_tx_count"],"is_fresh":bool(r["is_fresh"]),
                "score":r["score"],"tags":jloads(r["tags"],[]),
                "bridge_usd_24h":r["bridge_usd_24h"],"lp_usd_24h":r["lp_usd_24h"],
                "swap_usd_24h":r["swap_usd_24h"],"event_count_24h":r["event_count_24h"],
            })
    except Exception:
        hot=[]

    try:
        timeline=[]
        rows=d.execute('''SELECT id,ts,address,event_type,protocol,action,usd,token_pair,
                                 subject,tx_hash,block_number,metadata
                          FROM address_events ORDER BY id DESC LIMIT 80''').fetchall()
        for r in rows:
            timeline.append({
                "id":r["id"],"ts":r["ts"],"address":r["address"],
                "event_type":r["event_type"],"protocol":r["protocol"],
                "action":r["action"],"usd":r["usd"],"token_pair":r["token_pair"],
                "subject":r["subject"],"tx_hash":r["tx_hash"],
                "block_number":r["block_number"],"metadata":jloads(r["metadata"],{}),
            })
    except Exception:
        timeline=[]

    try:
        p0=d.execute(
            "SELECT COUNT(*) n FROM alerts WHERE ts>=? AND severity='P0'",
            (now-86400,)
        ).fetchone()["n"]
    except Exception:
        p0=0
    try:
        wallets=d.execute(
            "SELECT COUNT(*) n FROM address_profiles WHERE event_count_24h>0 AND last_seen_ts>=?",
            (now-86400,)
        ).fetchone()["n"]
    except Exception:
        wallets=0

    supervisor_hb=jint(d,"supervisor_heartbeat",0)
    supervisor_started=jint(d,"supervisor_started_at",0)
    supervisor_restarts=jint(d,"supervisor_component_restarts",0)
    self_restarts=jint(d,"supervisor_self_restarts",0)
    rss_mb=jfloat(d,"supervisor_rss_mb",0)
    thread_live=jint(d,"supervisor_threads_live",0)
    thread_expected=jint(d,"supervisor_threads_expected",0)
    expired_swap=int(metric(d,"swap_expired"))
    expired_fast=int(metric(d,"fast_expired"))
    db_mb=jfloat(d,"maintenance_db_mb",0)

    out={
        "version":"1.2.5",
        "supervisor_running":supervisor_hb>0 and now-supervisor_hb<30,
        "supervisor_uptime":max(0,now-supervisor_started) if supervisor_started else 0,
        "supervisor_restarts":supervisor_restarts,
        "supervisor_self_restarts":self_restarts,
        "rss_mb":round(rss_mb,1),
        "threads_live":thread_live,
        "threads_expected":thread_expected,
        "expired_swap":expired_swap,
        "expired_fast":expired_fast,
        "db_mb":round(db_mb,1),
        "running":hb>0 and now-hb<30,
        "heartbeat_age":now-hb if hb else None,
        "last_block":last,"head":head,"lag":max(0,head-last),
        "scanner_rpc_ms":jint(d,"fast_scanner_rpc_ms",0),
        "scanner_batch_ms":jint(d,"fast_scanner_batch_ms",0),

        "fast_pending":fast_pending,
        "fast_processing":fast_processing,
        "fast_deferred":fast_deferred,
        "fast_workers":fast_live,
        "fast_rate":round(fast_rate,2),

        "meta_pending":meta_pending,
        "meta_processing":meta_processing,
        "meta_live":bool(meta_hb and now-meta_hb<60),
        "meta_rate":round(meta_rate,2),
        "resolver_pending":resolver_pending,

        "swap_target":target,
        "swap_live":swap_live,
        "swap_rate":round(swap_rate,2),
        "swap_pending":swap_pending,
        "swap_processing":swap_processing,
        "swap_deferred":swap_deferred,

        "swap_candidates":int(metric(d,"swap_candidates")),
        "swap_confirmed":int(metric(d,"swap_confirmed")),
        "swap_small":int(metric(d,"swap_small")),
        "swap_unanchored":int(metric(d,"swap_unanchored")),
        "swap_wrong_pool":int(metric(d,"swap_wrong_pool")),
        "swap_no_input":int(metric(d,"swap_no_input")),
        "swap_zero_reserve":int(metric(d,"swap_zero_reserve")),
        "swap_other_unpriced":int(metric(d,"swap_other_unpriced")),
        "swap_errors":int(metric(d,"swap_errors")),
        "shadow_checked":int(metric(d,"swap_shadow_checked")),
        "shadow_missed":int(metric(d,"swap_shadow_missed")),
        "rpc_backoffs":int(metric(d,"swap_rpc_backoffs")),

        "native_running":bool(native_hb and now-native_hb<60),
        "native_lag":max(0,native_head-native_last),
        "native_chunk":jint(d,"native_scanner_chunk",0),

        "alerts24":count_alerts(),
        "p0_24":p0,
        "liquidity24":count_alerts("AND category='liquidity'"),
        "bridge24":count_alerts("AND category='bridge'"),
        "signal24":count_alerts("AND category='signal'"),
        "wallets24":wallets,
        "hot_wallets":hot,
        "timeline":timeline,
    }
    d.close()
    return out

def address_detail(addr):
    d=connect()
    a=(addr or "").lower()
    p=d.execute("SELECT * FROM address_profiles WHERE address=?",(a,)).fetchone()
    events=d.execute(
        "SELECT * FROM address_events WHERE address=? ORDER BY id DESC LIMIT 150",(a,)
    ).fetchall()
    out={"profile":dict(p) if p else None,"events":[]}
    if out["profile"]:
        out["profile"]["tags"]=jloads(out["profile"].get("tags"),[])
    for r in events:
        x=dict(r); x["metadata"]=jloads(x.get("metadata"),{}); out["events"].append(x)
    d.close()
    return out

HTML_ZH = r'''<!doctype html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Robinhood 链资金雷达 V1.2.5</title>
<style>
:root{color-scheme:dark;--bg:#070a0f;--card:#101722;--line:#202c3b;--muted:#8190a3;--good:#2fd07f;--hot:#ff5f65;--warn:#ffb547;--blue:#69aaff;--violet:#b28cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f5f7fb;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:auto;padding:18px 13px 42px}.head{display:flex;justify-content:space-between;align-items:center;gap:10px}.title{font-size:21px;font-weight:800}.sub{font-size:11px;color:var(--muted);margin-top:3px}
.badge,.tag,.tab{border:1px solid var(--line);border-radius:999px}.badge{padding:7px 10px;font-size:11px}.on{color:var(--good)}.off{color:var(--hot)}.warn{color:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;margin-top:14px}.card,.wallet,.event,.empty{background:var(--card);border:1px solid var(--line);border-radius:14px}.card{padding:12px}.k{font-size:10px;letter-spacing:.07em;color:var(--muted);text-transform:uppercase}.v{font-size:22px;font-weight:800;margin-top:3px}.sm{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.45}
.tabs{display:flex;gap:7px;overflow:auto;margin:15px 0 10px}.tab{padding:7px 11px;white-space:nowrap;font-size:12px;background:transparent;color:#c9d2df}.tab.active{background:#182235;color:#fff}
.panel{display:none}.panel.active{display:block}.section-title{font-size:14px;font-weight:750;margin:13px 2px 8px}.wallet{padding:12px;margin-bottom:8px}.row{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.addr{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;color:var(--blue);overflow-wrap:anywhere}.score{font-size:21px;font-weight:900}.score.hot{color:var(--hot)}.score.warm{color:var(--warn)}
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}.tag{font-size:10px;padding:4px 7px;color:#c8d2df}.tag.hot{color:var(--hot);border-color:#6b3035}.moneyline{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.65}
.event{padding:11px;margin-bottom:7px;border-left:3px solid var(--line)}.event.bridge{border-left-color:var(--violet)}.event.liquidity{border-left-color:var(--warn)}.event.swap{border-left-color:var(--blue)}.etype{font-size:12px;font-weight:800}.money{font-weight:850;color:var(--warn)}.meta{font-size:10.5px;color:var(--muted);line-height:1.55;margin-top:5px;overflow-wrap:anywhere}
a{color:var(--blue);text-decoration:none}.empty{text-align:center;padding:28px;color:var(--muted)}footer{font-size:10px;color:var(--muted);text-align:center;margin-top:20px}
@media(min-width:760px){.grid{grid-template-columns:repeat(5,1fr)}}
</style></head><body><main>
<div class="head"><div><div class="title">Robinhood 链资金雷达 <span style="color:var(--blue)">V1.2.5</span></div><div class="sub">手机常驻版 · 实时优先 · 主网 4663 · 仅本机访问 · <a href="/en">English</a></div></div><div id="status" class="badge">连接中</div></div>
<div class="grid">
<div class="card"><div class="k">系统守护</div><div id="supervisor" class="v">—</div><div id="supervisorSub" class="sm">单进程守护</div></div>
<div class="card"><div class="k">运行时长</div><div id="uptime" class="v">—</div><div id="memory" class="sm">内存占用</div></div>
<div class="card"><div class="k">实时扫链</div><div id="scanner" class="v">—</div><div id="hb" class="sm">心跳</div></div>
<div class="card"><div class="k">区块延迟</div><div id="lagv" class="v">—</div><div id="block" class="sm">当前区块</div></div>
<div class="card"><div class="k">跨链 / LP 队列</div><div id="fastQ" class="v">0</div><div id="fastSub" class="sm">高优先通道</div></div>
<div class="card"><div class="k">池子元数据队列</div><div id="metaQ" class="v">0</div><div id="metaSub" class="sm">后台解析通道</div></div>
<div class="card"><div class="k">Swap 过滤器</div><div id="swapFilters" class="v">—</div><div id="swapRate" class="sm">自适应并发</div></div>
<div class="card"><div class="k">Swap 积压</div><div id="swapQ" class="v">0</div><div id="swapQSub" class="sm">待处理</div></div>
<div class="card"><div class="k">大额候选</div><div id="candidates" class="v">0</div><div id="confirmed" class="sm">最终确认 0</div></div>
<div class="card"><div class="k">过滤统计</div><div id="small" class="v">0</div><div id="reasons" class="sm">小额 / 无锚定价格</div></div>
<div class="card"><div class="k">抽样复核</div><div id="shadow" class="v">0</div><div id="shadowSub" class="sm">漏检 0</div></div>
<div class="card"><div class="k">扫链 RPC 延迟</div><div id="rpc" class="v">—</div><div id="rpcSub" class="sm">接口响应</div></div>
<div class="card"><div class="k">原生 ETH 扫描延迟</div><div id="nativeLag" class="v">—</div><div id="nativeSub" class="sm">ETH 跨链存入</div></div>
<div class="card"><div class="k">热点资金地址</div><div id="wallets" class="v">0</div><div class="sm">近 24 小时已跟踪</div></div>
<div class="card"><div class="k">P0 强信号</div><div id="p0" class="v">0</div><div id="alerts" class="sm">警报 0</div></div>
</div>
<div class="tabs"><button class="tab active" data-p="hot">热点地址</button><button class="tab" data-p="timeline">资金时间线</button><button class="tab" data-p="pipeline">运行管线</button></div>
<section id="hot" class="panel active"><div class="section-title">资金地址画像</div><div id="hotlist"></div><div id="addressDetail"></div></section>
<section id="timeline" class="panel"><div class="section-title">全链大额资金行为时间线</div><div id="timelineList"></div></section>
<section id="pipeline" class="panel"><div class="section-title">V1.2.5 实时资金监控管线</div><div class="card"><div class="moneyline" id="pipelineText">正在读取运行状态...</div></div></section>
<footer>每 3 秒刷新 · 单 Python 进程 · 自动守护 · 日志轮转 · 仅 127.0.0.1 本机访问</footer>
</main><script>
const X='https://robinhoodchain.blockscout.com', $=id=>document.getElementById(id);
function money(v){return v==null?'—':'$'+Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}
function short(a){return a?(a.slice(0,8)+'…'+a.slice(-6)):'—'}
function ago(ts){let s=Math.max(0,Math.floor(Date.now()/1000-ts));if(s<60)return s+'秒';if(s<3600)return Math.floor(s/60)+'分钟';if(s<86400)return Math.floor(s/3600)+'小时';return Math.floor(s/86400)+'天'}
function duration(s){s=Number(s||0);if(s<3600)return Math.floor(s/60)+'分钟';if(s<86400)return Math.floor(s/3600)+'小时 '+Math.floor((s%3600)/60)+'分钟';return Math.floor(s/86400)+'天 '+Math.floor((s%86400)/3600)+'小时'}
const TAG_CN={'HOT':'热点','FRESH':'新地址','WHALE BRIDGE':'巨鲸跨链','ACTIVE SWAP':'活跃 Swap','LP DEPLOY':'LP 部署','NEW POOL':'新池','BRIDGE→LP':'跨链→LP'};
const ACTION_CN={'ADD':'加池','REMOVE':'撤池','NEW POOL ADD':'新池加池','SWAP':'Swap 兑换','BRIDGE IN':'跨链流入','CUMULATIVE':'累计流入','BRIDGE→LP':'跨链→LP'};
function tagCN(t){return TAG_CN[t]||t}
function actionCN(a){return ACTION_CN[a]||a}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab,.panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(b.dataset.p).classList.add('active')});
function walletHTML(w){let sc=w.score||0,cls=sc>=80?'hot':sc>=50?'warm':'';return `<div class="wallet"><div class="row"><div><a class="addr" href="${X}/address/${w.address}" target="_blank">${short(w.address)}</a><div class="tags">${(w.tags||[]).map(t=>`<span class="tag ${t==='HOT'?'hot':''}">${tagCN(t)}</span>`).join('')}</div></div><div class="score ${cls}">${sc}</div></div><div class="moneyline">跨链 ${money(w.bridge_usd_24h)} · LP ${money(w.lp_usd_24h)} · Swap ${money(w.swap_usd_24h)}<br>近24小时 ${w.event_count_24h} 个事件 · 最后活跃于 ${ago(w.last_seen_ts)}前<br><a href="#" onclick="openAddress('${w.address}');return false">查看本地时间线 ↓</a></div></div>`}
function eventHTML(e){return `<div class="event ${e.event_type}"><div class="row"><div class="etype">${e.protocol} · ${actionCN(e.action)}</div><div class="money">${money(e.usd)}</div></div><div class="meta"><a href="${X}/address/${e.address}" target="_blank">${short(e.address)}</a>${e.token_pair?' · '+e.token_pair:''}<br>区块 ${e.block_number||'—'} · ${ago(e.ts)}前${e.tx_hash?` · <a href="${X}/tx/${e.tx_hash}" target="_blank">查看交易 ↗</a>`:''}</div></div>`}
async function openAddress(a){try{const d=await fetch('/api/address?address='+encodeURIComponent(a),{cache:'no-store'}).then(r=>r.json());const p=d.profile||{};$('addressDetail').innerHTML=`<div class="section-title">地址时间线 · ${short(a)} · 评分 ${p.score??'—'}</div>`+(d.events&&d.events.length?d.events.map(eventHTML).join(''):'<div class="empty">该地址暂无事件</div>');$('addressDetail').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){$('addressDetail').innerHTML='<div class="empty">地址时间线读取失败</div>'}}
async function refresh(){try{const d=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());
$('supervisor').textContent=d.supervisor_running?'运行中':'异常';$('supervisor').className='v '+(d.supervisor_running?'':'warn');$('supervisorSub').textContent=`线程 ${d.threads_live}/${d.threads_expected} · 组件重启 ${d.supervisor_restarts} · 整体自愈 ${d.supervisor_self_restarts}`;
$('uptime').textContent=duration(d.supervisor_uptime);$('memory').textContent=`内存 ${d.rss_mb} MB · 数据库 ${d.db_mb} MB`;
$('status').textContent=d.running?'● 正常运行':'● 扫链异常';$('status').className='badge '+(d.running?'on':'off');
$('scanner').textContent=d.running?'实时':'停滞';$('hb').textContent='心跳 '+(d.heartbeat_age??'—')+' 秒';
$('lagv').textContent=d.lag;$('block').textContent='已扫描至 '+Number(d.last_block).toLocaleString();
$('fastQ').textContent=d.fast_pending;$('fastSub').textContent=`处理中 ${d.fast_processing} · 待解析 ${d.fast_deferred} · 工作线程 ${d.fast_workers}/2 · ${Number(d.fast_rate).toFixed(1)}/秒`;
$('metaQ').textContent=d.meta_pending;$('metaSub').textContent=`处理中 ${d.meta_processing} · ${d.meta_live?'正常':'异常'} · ${Number(d.meta_rate).toFixed(1)}/秒`;
$('swapFilters').textContent=d.swap_live+'/'+d.swap_target;$('swapRate').textContent=Number(d.swap_rate).toFixed(1)+'/秒 · 自适应目标';
$('swapQ').textContent=d.swap_pending;$('swapQSub').textContent=`处理中 ${d.swap_processing} · 待解析 ${d.swap_deferred}`;
$('candidates').textContent=d.swap_candidates;$('confirmed').textContent='最终确认 '+d.swap_confirmed;
$('small').textContent=d.swap_small;$('reasons').textContent=`无锚定价格 ${d.swap_unanchored} · 非目标池 ${d.swap_wrong_pool} · 无输入量 ${d.swap_no_input}`;
$('shadow').textContent=d.shadow_checked;$('shadowSub').textContent=`漏检 ${d.shadow_missed} · 错误 ${d.swap_errors}`;
$('rpc').textContent=d.scanner_rpc_ms+' ms';$('rpcSub').textContent=`日志查询 ${d.scanner_batch_ms} ms · 限流退避 ${d.rpc_backoffs}`;
$('nativeLag').textContent=d.native_lag;$('nativeSub').textContent=`${d.native_running?'正常':'异常'} · 每批 ${d.native_chunk} 区块`;
$('wallets').textContent=d.wallets24;$('p0').textContent=d.p0_24;$('alerts').textContent='近24小时警报 '+d.alerts24;
$('pipelineText').innerHTML=`<b>手机常驻守护：</b>单 Python 进程运行，自动看门狗、自愈重启、日志自动轮转<br><b>实时优先：</b>已过期 Swap ${d.expired_swap} · 已过期 LP ${d.expired_fast}<br><br><b>高优先通道：</b>跨链 / LP / V4 ModifyLiquidity → 2 个专用工作线程<br><b>元数据通道：</b>PairCreated / PoolCreated / V4 Initialize → 1 个后台线程<br><b>Swap 通道：</b>最多 3 个线程；根据 RPC 压力自动在 3 / 2 / 1 路之间调整<br><br><b>过滤结果：</b>候选 ${d.swap_candidates} · 最终确认 ${d.swap_confirmed} · 小额 ${d.swap_small} · 无锚定价格 ${d.swap_unanchored} · 零储备 ${d.swap_zero_reserve} · 其他无法定价 ${d.swap_other_unpriced}<br><b>抽样复核：</b>已抽样 ${d.shadow_checked} · 快速过滤漏检 ${d.shadow_missed}<br><b>V4 池解析：</b>待解析 ${d.resolver_pending}`;
$('hotlist').innerHTML=d.hot_wallets.length?d.hot_wallets.map(walletHTML).join(''):'<div class="empty">暂时没有达到画像门槛的地址</div>';
$('timelineList').innerHTML=d.timeline.length?d.timeline.map(eventHTML).join(''):'<div class="empty">暂时没有 ≥ $100K 行为事件</div>';
}catch(e){$('status').textContent='● DASHBOARD ERROR';$('status').className='badge off'}}
refresh();setInterval(refresh,3000);
</script></body></html>'''

HTML_EN = r'''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Robinhood Chain Radar V1.2.5</title>
<style>
:root{color-scheme:dark;--bg:#070a0f;--card:#101722;--line:#202c3b;--muted:#8190a3;--good:#2fd07f;--hot:#ff5f65;--warn:#ffb547;--blue:#69aaff;--violet:#b28cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f5f7fb;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:auto;padding:18px 13px 42px}.head{display:flex;justify-content:space-between;align-items:center;gap:10px}.title{font-size:21px;font-weight:800}.sub{font-size:11px;color:var(--muted);margin-top:3px}
.badge,.tag,.tab{border:1px solid var(--line);border-radius:999px}.badge{padding:7px 10px;font-size:11px}.on{color:var(--good)}.off{color:var(--hot)}.warn{color:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;margin-top:14px}.card,.wallet,.event,.empty{background:var(--card);border:1px solid var(--line);border-radius:14px}.card{padding:12px}.k{font-size:10px;letter-spacing:.07em;color:var(--muted);text-transform:uppercase}.v{font-size:22px;font-weight:800;margin-top:3px}.sm{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.45}
.tabs{display:flex;gap:7px;overflow:auto;margin:15px 0 10px}.tab{padding:7px 11px;white-space:nowrap;font-size:12px;background:transparent;color:#c9d2df}.tab.active{background:#182235;color:#fff}
.panel{display:none}.panel.active{display:block}.section-title{font-size:14px;font-weight:750;margin:13px 2px 8px}.wallet{padding:12px;margin-bottom:8px}.row{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.addr{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;color:var(--blue);overflow-wrap:anywhere}.score{font-size:21px;font-weight:900}.score.hot{color:var(--hot)}.score.warm{color:var(--warn)}
.tags{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}.tag{font-size:10px;padding:4px 7px;color:#c8d2df}.tag.hot{color:var(--hot);border-color:#6b3035}.moneyline{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.65}
.event{padding:11px;margin-bottom:7px;border-left:3px solid var(--line)}.event.bridge{border-left-color:var(--violet)}.event.liquidity{border-left-color:var(--warn)}.event.swap{border-left-color:var(--blue)}.etype{font-size:12px;font-weight:800}.money{font-weight:850;color:var(--warn)}.meta{font-size:10.5px;color:var(--muted);line-height:1.55;margin-top:5px;overflow-wrap:anywhere}
a{color:var(--blue);text-decoration:none}.empty{text-align:center;padding:28px;color:var(--muted)}footer{font-size:10px;color:var(--muted);text-align:center;margin-top:20px}
@media(min-width:760px){.grid{grid-template-columns:repeat(5,1fr)}}
</style></head><body><main>
<div class="head"><div><div class="title">Robinhood Chain Radar <span style="color:var(--blue)">V1.2.5</span></div><div class="sub">Mobile Supervisor · Realtime Priority · Mainnet 4663 · localhost only · <a href="/zh">中文</a></div></div><div id="status" class="badge">连接中</div></div>
<div class="grid">
<div class="card"><div class="k">Supervisor</div><div id="supervisor" class="v">—</div><div id="supervisorSub" class="sm">single-process</div></div>
<div class="card"><div class="k">Uptime</div><div id="uptime" class="v">—</div><div id="memory" class="sm">RSS</div></div>
<div class="card"><div class="k">Fast Scanner</div><div id="scanner" class="v">—</div><div id="hb" class="sm">heartbeat</div></div>
<div class="card"><div class="k">Block Lag</div><div id="lagv" class="v">—</div><div id="block" class="sm">block</div></div>
<div class="card"><div class="k">Bridge / LP Queue</div><div id="fastQ" class="v">0</div><div id="fastSub" class="sm">fast lane</div></div>
<div class="card"><div class="k">Metadata Queue</div><div id="metaQ" class="v">0</div><div id="metaSub" class="sm">background lane</div></div>
<div class="card"><div class="k">Swap Filters</div><div id="swapFilters" class="v">—</div><div id="swapRate" class="sm">adaptive</div></div>
<div class="card"><div class="k">Swap Backlog</div><div id="swapQ" class="v">0</div><div id="swapQSub" class="sm">pending</div></div>
<div class="card"><div class="k">Candidates</div><div id="candidates" class="v">0</div><div id="confirmed" class="sm">confirmed 0</div></div>
<div class="card"><div class="k">Discard Reasons</div><div id="small" class="v">0</div><div id="reasons" class="sm">small / unanchored</div></div>
<div class="card"><div class="k">Shadow Check</div><div id="shadow" class="v">0</div><div id="shadowSub" class="sm">missed 0</div></div>
<div class="card"><div class="k">Scanner RPC</div><div id="rpc" class="v">—</div><div id="rpcSub" class="sm">latency</div></div>
<div class="card"><div class="k">Native Lag</div><div id="nativeLag" class="v">—</div><div id="nativeSub" class="sm">ETH deposits</div></div>
<div class="card"><div class="k">Hot Wallets</div><div id="wallets" class="v">0</div><div class="sm">24h tracked</div></div>
<div class="card"><div class="k">P0 Signals</div><div id="p0" class="v">0</div><div id="alerts" class="sm">alerts 0</div></div>
</div>
<div class="tabs"><button class="tab active" data-p="hot">Hot Wallets</button><button class="tab" data-p="timeline">Capital Timeline</button><button class="tab" data-p="pipeline">Pipeline</button></div>
<section id="hot" class="panel active"><div class="section-title">资金地址画像</div><div id="hotlist"></div><div id="addressDetail"></div></section>
<section id="timeline" class="panel"><div class="section-title">全链大额行为时间线</div><div id="timelineList"></div></section>
<section id="pipeline" class="panel"><div class="section-title">V1.2.3 自适应流水线</div><div class="card"><div class="moneyline" id="pipelineText">loading...</div></div></section>
<footer>每 3 秒刷新 · Single Python process · watchdog · rotating log · 127.0.0.1 only</footer>
</main><script>
const X='https://robinhoodchain.blockscout.com', $=id=>document.getElementById(id);
function money(v){return v==null?'—':'$'+Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}
function short(a){return a?(a.slice(0,8)+'…'+a.slice(-6)):'—'}
function ago(ts){let s=Math.max(0,Math.floor(Date.now()/1000-ts));if(s<60)return s+'s';if(s<3600)return Math.floor(s/60)+'m';if(s<86400)return Math.floor(s/3600)+'h';return Math.floor(s/86400)+'d'} function duration(s){s=Number(s||0);if(s<3600)return Math.floor(s/60)+'m';if(s<86400)return Math.floor(s/3600)+'h '+Math.floor((s%3600)/60)+'m';return Math.floor(s/86400)+'d '+Math.floor((s%86400)/3600)+'h'}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab,.panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(b.dataset.p).classList.add('active')});
function walletHTML(w){let sc=w.score||0,cls=sc>=80?'hot':sc>=50?'warm':'';return `<div class="wallet"><div class="row"><div><a class="addr" href="${X}/address/${w.address}" target="_blank">${short(w.address)}</a><div class="tags">${(w.tags||[]).map(t=>`<span class="tag ${t==='HOT'?'hot':''}">${t}</span>`).join('')}</div></div><div class="score ${cls}">${sc}</div></div><div class="moneyline">Bridge ${money(w.bridge_usd_24h)} · LP ${money(w.lp_usd_24h)} · Swap ${money(w.swap_usd_24h)}<br>${w.event_count_24h} events · last ${ago(w.last_seen_ts)} ago<br><a href="#" onclick="openAddress('${w.address}');return false">本地时间线 ↓</a></div></div>`}
function eventHTML(e){return `<div class="event ${e.event_type}"><div class="row"><div class="etype">${e.protocol} · ${e.action}</div><div class="money">${money(e.usd)}</div></div><div class="meta"><a href="${X}/address/${e.address}" target="_blank">${short(e.address)}</a>${e.token_pair?' · '+e.token_pair:''}<br>Block ${e.block_number||'—'} · ${ago(e.ts)} ago${e.tx_hash?` · <a href="${X}/tx/${e.tx_hash}" target="_blank">Tx ↗</a>`:''}</div></div>`}
async function openAddress(a){try{const d=await fetch('/api/address?address='+encodeURIComponent(a),{cache:'no-store'}).then(r=>r.json());const p=d.profile||{};$('addressDetail').innerHTML=`<div class="section-title">地址时间线 · ${short(a)} · Score ${p.score??'—'}</div>`+(d.events&&d.events.length?d.events.map(eventHTML).join(''):'<div class="empty">该地址暂无事件</div>');$('addressDetail').scrollIntoView({behavior:'smooth',block:'start'})}catch(e){$('addressDetail').innerHTML='<div class="empty">地址时间线读取失败</div>'}}
async function refresh(){try{const d=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());
$('supervisor').textContent=d.supervisor_running?'LIVE':'STALE';$('supervisor').className='v '+(d.supervisor_running?'':'warn');$('supervisorSub').textContent=`threads ${d.threads_live}/${d.threads_expected} · restarts ${d.supervisor_restarts}/${d.supervisor_self_restarts}`;
$('uptime').textContent=duration(d.supervisor_uptime);$('memory').textContent=`RSS ${d.rss_mb} MB · DB ${d.db_mb} MB`;
$('status').textContent=d.running?'● RUNNING':'● SCANNER STALE';$('status').className='badge '+(d.running?'on':'off');
$('scanner').textContent=d.running?'LIVE':'STALE';$('hb').textContent=(d.heartbeat_age??'—')+'s heartbeat';
$('lagv').textContent=d.lag;$('block').textContent='block '+Number(d.last_block).toLocaleString();
$('fastQ').textContent=d.fast_pending;$('fastSub').textContent=`processing ${d.fast_processing} · deferred ${d.fast_deferred} · ${d.fast_workers}/2 · ${Number(d.fast_rate).toFixed(1)}/s`;
$('metaQ').textContent=d.meta_pending;$('metaSub').textContent=`processing ${d.meta_processing} · ${d.meta_live?'LIVE':'STALE'} · ${Number(d.meta_rate).toFixed(1)}/s`;
$('swapFilters').textContent=d.swap_live+'/'+d.swap_target;$('swapRate').textContent=Number(d.swap_rate).toFixed(1)+'/s · adaptive target';
$('swapQ').textContent=d.swap_pending;$('swapQSub').textContent=`processing ${d.swap_processing} · deferred ${d.swap_deferred}`;
$('candidates').textContent=d.swap_candidates;$('confirmed').textContent='confirmed '+d.swap_confirmed;
$('small').textContent=d.swap_small;$('reasons').textContent=`unanchored ${d.swap_unanchored} · wrong ${d.swap_wrong_pool} · no-input ${d.swap_no_input}`;
$('shadow').textContent=d.shadow_checked;$('shadowSub').textContent=`missed ${d.shadow_missed} · errors ${d.swap_errors}`;
$('rpc').textContent=d.scanner_rpc_ms+' ms';$('rpcSub').textContent=`getLogs ${d.scanner_batch_ms} ms · backoff ${d.rpc_backoffs}`;
$('nativeLag').textContent=d.native_lag;$('nativeSub').textContent=`${d.native_running?'LIVE':'STALE'} · chunk ${d.native_chunk}`;
$('wallets').textContent=d.wallets24;$('p0').textContent=d.p0_24;$('alerts').textContent='alerts '+d.alerts24;
$('pipelineText').innerHTML=`<b>Mobile Supervisor:</b> one Python process, watchdog, rotating log<br><b>Freshness:</b> expired Swap ${d.expired_swap} · expired LP ${d.expired_fast}<br><br><b>Fast lane:</b> Bridge / LP / V4 ModifyLiquidity → 2 dedicated workers<br><b>Metadata lane:</b> PairCreated / PoolCreated / V4 Initialize → 1 background worker<br><b>Swap lane:</b> up to 3 workers; RPC pressure automatically chooses 3 / 2 / 1<br><br><b>Filter result:</b> candidates ${d.swap_candidates}, confirmed ${d.swap_confirmed}, small ${d.swap_small}, unanchored ${d.swap_unanchored}, zero-reserve ${d.swap_zero_reserve}, other ${d.swap_other_unpriced}<br><b>Shadow audit:</b> ${d.shadow_checked} sampled · ${d.shadow_missed} missed by cheap filter<br><b>V4 resolver:</b> ${d.resolver_pending} pending`;
$('hotlist').innerHTML=d.hot_wallets.length?d.hot_wallets.map(walletHTML).join(''):'<div class="empty">暂时没有达到画像门槛的地址</div>';
$('timelineList').innerHTML=d.timeline.length?d.timeline.map(eventHTML).join(''):'<div class="empty">暂时没有 ≥ $100K 行为事件</div>';
}catch(e){$('status').textContent='● DASHBOARD ERROR';$('status').className='badge off'}}
refresh();setInterval(refresh,3000);
</script></body></html>'''

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def sendb(self,code,ctype,b):
        self.send_response(code); self.send_header("Content-Type",ctype); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u=urlparse(self.path)
        if u.path=="/api/status":
            try:self.sendb(200,"application/json; charset=utf-8",json.dumps(snapshot(),ensure_ascii=False).encode())
            except Exception as e:self.sendb(500,"application/json",json.dumps({"error":str(e)}).encode())
        elif u.path=="/api/address":
            a=(parse_qs(u.query).get("address") or [""])[0]
            try:self.sendb(200,"application/json; charset=utf-8",json.dumps(address_detail(a),ensure_ascii=False).encode())
            except Exception as e:self.sendb(500,"application/json",json.dumps({"error":str(e)}).encode())
        elif u.path in ("/", "/zh"):
            self.sendb(200,"text/html; charset=utf-8",HTML_ZH.encode())
        elif u.path=="/en":
            self.sendb(200,"text/html; charset=utf-8",HTML_EN.encode())
        else:self.sendb(404,"text/plain",b"404")

def run_server():
    server=ThreadingHTTPServer((HOST,PORT),H)
    print(f"Dashboard V1.2.5: http://{HOST}:{PORT}",flush=True)
    server.serve_forever(poll_interval=0.5)

if __name__=="__main__":
    run_server()

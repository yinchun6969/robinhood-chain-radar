#!/usr/bin/env python3
import json
import time
import logging

ZERO = "0x0000000000000000000000000000000000000000"
DEAD = "0x000000000000000000000000000000000000dead"
log = logging.getLogger("token-radar")


class TokenRadar:
    """Token-centric capital-flow intelligence.

    V1.3.0 keeps the realtime event workers cheap: event handlers only persist a
    compact token event and enqueue the token. A dedicated background worker
    performs holder/contract analysis, scoring and alert correlation.
    """

    def __init__(self, db, token_intel, token_getter, telegram, save_alert, explorer,
                 weth, usdg, language="zh_CN", min_event_usd=100_000,
                 signal_min_score=55, correlation_window_min=180,
                 deep_scan_ttl_sec=600, signal_cooldown_min=30):
        self.db = db
        self.token_intel = token_intel
        self.token_getter = token_getter
        self.telegram = telegram
        self.save_alert = save_alert
        self.explorer = explorer.rstrip("/")
        self.weth = (weth or "").lower()
        self.usdg = (usdg or "").lower()
        self.language = language or "zh_CN"
        self.min_event_usd = float(min_event_usd)
        self.signal_min_score = int(signal_min_score)
        self.correlation_window = int(correlation_window_min) * 60
        self.deep_scan_ttl = int(deep_scan_ttl_sec)
        self.signal_cooldown = max(60, int(signal_cooldown_min) * 60)
        self._ensure_schema()

    @property
    def zh(self):
        return self.language.lower().startswith("zh")

    def _ensure_schema(self):
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS token_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts INTEGER NOT NULL,
          token TEXT NOT NULL,
          symbol TEXT,
          event_type TEXT NOT NULL,
          action TEXT NOT NULL,
          usd REAL,
          actor TEXT,
          pool TEXT,
          protocol TEXT,
          tx_hash TEXT,
          block_number INTEGER,
          metadata TEXT,
          UNIQUE(tx_hash,token,event_type,action)
        )
        """)
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS token_profiles (
          token TEXT PRIMARY KEY,
          symbol TEXT,
          first_seen_ts INTEGER NOT NULL,
          last_seen_ts INTEGER NOT NULL,
          first_seen_block INTEGER,
          last_seen_block INTEGER,
          event_count_24h INTEGER NOT NULL DEFAULT 0,
          buy_usd_24h REAL NOT NULL DEFAULT 0,
          sell_usd_24h REAL NOT NULL DEFAULT 0,
          lp_add_usd_24h REAL NOT NULL DEFAULT 0,
          lp_remove_usd_24h REAL NOT NULL DEFAULT 0,
          bridge_usd_24h REAL NOT NULL DEFAULT 0,
          unique_wallets_24h INTEGER NOT NULL DEFAULT 0,
          hot_wallets_24h INTEGER NOT NULL DEFAULT 0,
          pool_count_24h INTEGER NOT NULL DEFAULT 0,
          lp_drain_ratio REAL NOT NULL DEFAULT 0,
          capital_score INTEGER NOT NULL DEFAULT 0,
          risk_score INTEGER NOT NULL DEFAULT 0,
          signal_score INTEGER NOT NULL DEFAULT 0,
          signal_level TEXT NOT NULL DEFAULT 'WATCH',
          tags TEXT NOT NULL DEFAULT '[]',
          holders_json TEXT,
          risk_json TEXT,
          sequence_json TEXT,
          last_deep_scan_ts INTEGER NOT NULL DEFAULT 0,
          updated_at INTEGER NOT NULL DEFAULT 0
        )
        """)
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS token_scan_queue (
          token TEXT PRIMARY KEY,
          symbol TEXT,
          status INTEGER NOT NULL DEFAULT 0,
          attempts INTEGER NOT NULL DEFAULT 0,
          claimed_at INTEGER,
          last_error TEXT,
          priority INTEGER NOT NULL DEFAULT 50,
          updated_at INTEGER NOT NULL
        )
        """)
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS token_signals (
          signal_key TEXT PRIMARY KEY,
          ts INTEGER NOT NULL,
          token TEXT NOT NULL,
          symbol TEXT,
          level TEXT NOT NULL,
          signal_type TEXT NOT NULL,
          score INTEGER NOT NULL,
          risk_score INTEGER NOT NULL,
          details TEXT
        )
        """)
        # Forward-compatible column migration for early V1.3 development DBs.
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(token_profiles)").fetchall()}
        if "pool_count_24h" not in cols:
            self.db.execute("ALTER TABLE token_profiles ADD COLUMN pool_count_24h INTEGER NOT NULL DEFAULT 0")
        if "lp_drain_ratio" not in cols:
            self.db.execute("ALTER TABLE token_profiles ADD COLUMN lp_drain_ratio REAL NOT NULL DEFAULT 0")
        qcols = {r[1] for r in self.db.execute("PRAGMA table_info(token_scan_queue)").fetchall()}
        if "priority" not in qcols:
            self.db.execute("ALTER TABLE token_scan_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 50")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_token_events_token_ts ON token_events(token,ts DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_token_events_actor_ts ON token_events(actor,ts DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_token_profiles_score ON token_profiles(signal_score DESC,last_seen_ts DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_token_signals_ts ON token_signals(ts DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_token_queue_priority ON token_scan_queue(status,priority DESC,updated_at)")
        self.db.commit()

    @staticmethod
    def norm(addr):
        return (addr or "").lower()

    def is_base(self, addr):
        return self.norm(addr) in {"", ZERO, self.weth, self.usdg}

    def tracked_sides(self, t0, t1):
        """Return token sides that deserve their own radar profile.

        WETH/USDG/native pairs produce one focus token. A token/token pool
        produces two profiles from the same event so neither early asset is
        silently missed.
        """
        a0, a1 = self.norm(t0.address), self.norm(t1.address)
        b0, b1 = self.is_base(a0), self.is_base(a1)
        if b0 and b1:
            return []
        if b0 and not b1:
            return [(t1, t0, 1)]
        if b1 and not b0:
            return [(t0, t1, 0)]
        return [(t0, t1, 0), (t1, t0, 1)]

    def focus_token(self, t0, t1):
        sides = self.tracked_sides(t0, t1)
        if sides:
            return sides[0]
        return t1, t0, 1

    def _ensure_profile(self, token, symbol, block):
        now = int(time.time())
        self.db.execute("""
          INSERT OR IGNORE INTO token_profiles(
            token,symbol,first_seen_ts,last_seen_ts,first_seen_block,last_seen_block,updated_at
          ) VALUES(?,?,?,?,?,?,?)
        """, (token, symbol, now, now, int(block or 0), int(block or 0), now))
        self.db.execute("""
          UPDATE token_profiles SET symbol=?,last_seen_ts=?,last_seen_block=?,updated_at=? WHERE token=?
        """, (symbol, now, int(block or 0), now, token))

    def _enqueue(self, token, symbol, priority=50):
        now = int(time.time())
        self.db.execute("""
          INSERT INTO token_scan_queue(token,symbol,status,attempts,claimed_at,last_error,priority,updated_at)
          VALUES(?,?,0,0,NULL,NULL,?,?)
          ON CONFLICT(token) DO UPDATE SET
            symbol=excluded.symbol,status=0,claimed_at=NULL,last_error=NULL,
            priority=excluded.priority,updated_at=excluded.updated_at
        """, (token, symbol, int(priority), now))

    def _record(self, token, symbol, event_type, action, usd, actor, pool,
                protocol, tx_hash, block_number, metadata=None):
        token = self.norm(token)
        if self.is_base(token):
            return
        if usd is not None and float(usd or 0) < self.min_event_usd:
            return
        actor = self.norm(actor)
        pool = self.norm(pool)
        now = int(time.time())
        self._ensure_profile(token, symbol, block_number)
        self.db.execute("""
          INSERT OR IGNORE INTO token_events(
            ts,token,symbol,event_type,action,usd,actor,pool,protocol,tx_hash,block_number,metadata
          ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (now, token, symbol, event_type, action, float(usd or 0), actor, pool,
              protocol, tx_hash, int(block_number or 0),
              json.dumps(dict(metadata or {}), ensure_ascii=False, separators=(",", ":"))))
        priority = 50
        amount = float(usd or 0)
        if amount >= 1_000_000:
            priority += 35
        elif amount >= 250_000:
            priority += 20
        elif amount >= 100_000:
            priority += 10
        if event_type == "bridge":
            priority += 15
        elif event_type == "liquidity":
            priority += 10
            if "REMOVE" in (action or "").upper():
                priority += 10
            if bool((metadata or {}).get("new_pool")):
                priority += 10
        self._enqueue(token, symbol, min(100, priority))
        self.db.commit()

    def observe_liquidity(self, kind, action, pool, usd, t0, t1, actor, tx_hash,
                          block_number, new_pool=False, metadata=None):
        for focus, other, idx in self.tracked_sides(t0, t1):
            meta = dict(metadata or {})
            meta.update({
                "token0": self.norm(t0.address), "token1": self.norm(t1.address),
                "other_token": self.norm(other.address), "new_pool": bool(new_pool),
                "focus_index": idx,
            })
            self._record(focus.address, focus.symbol, "liquidity", action, usd, actor,
                         pool, f"Uniswap {str(kind).upper()}", tx_hash, block_number, meta)

    def observe_swap(self, kind, pool, usd, t0, t1, raw0, raw1, actor, tx_hash,
                     block_number, metadata=None):
        for focus, other, idx in self.tracked_sides(t0, t1):
            raw_focus = int(raw0 if idx == 0 else raw1)
            # Pool event sign convention: positive = token enters pool (actor sells),
            # negative = token leaves pool (actor buys).
            direction = "BUY" if raw_focus < 0 else "SELL" if raw_focus > 0 else "SWAP"
            meta = dict(metadata or {})
            meta.update({
                "token0": self.norm(t0.address), "token1": self.norm(t1.address),
                "other_token": self.norm(other.address), "focus_index": idx,
                "raw_focus_sign": -1 if raw_focus < 0 else 1 if raw_focus > 0 else 0,
            })
            self._record(focus.address, focus.symbol, "swap", direction, usd, actor,
                         pool, f"Uniswap {str(kind).upper()}", tx_hash, block_number, meta)

    def observe_bridge(self, token, symbol, usd, recipient, protocol, tx_hash, block_number, metadata=None):
        self._record(token, symbol, "bridge", "BRIDGE IN", usd, recipient, recipient,
                     protocol, tx_hash, block_number, metadata)

    def _claim(self):
        now = int(time.time())
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("""
              SELECT token,symbol,updated_at FROM token_scan_queue
              WHERE status=0 ORDER BY priority DESC,updated_at ASC LIMIT 1
            """).fetchone()
            if not row:
                self.db.execute("COMMIT")
                return None
            token, symbol, updated_at = row
            self.db.execute("UPDATE token_scan_queue SET status=1,claimed_at=? WHERE token=?",
                            (now, token))
            self.db.execute("COMMIT")
            return token, symbol, int(updated_at), now
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _queue_done(self, token, queued_at):
        # If a newer event arrived during analysis, _enqueue() reset status to 0
        # and moved updated_at forward. Do not overwrite that pending work.
        self.db.execute("""
          UPDATE token_scan_queue SET status=2,claimed_at=NULL,last_error=NULL
          WHERE token=? AND status=1 AND updated_at<=?
        """, (token, queued_at))
        self.db.commit()

    def _queue_error(self, token, err):
        now = int(time.time())
        row = self.db.execute("SELECT attempts FROM token_scan_queue WHERE token=?", (token,)).fetchone()
        attempts = int(row[0] if row else 0) + 1
        self.db.execute("""
          UPDATE token_scan_queue SET status=?,attempts=?,claimed_at=NULL,last_error=?,updated_at=?
          WHERE token=?
        """, (3 if attempts >= 5 else 0, attempts, str(err)[:500], now, token))
        self.db.commit()

    def _sequence(self, token, rows):
        by_actor = {}
        for r in rows:
            actor = self.norm(r[6])
            if actor:
                by_actor.setdefault(actor, []).append(r)
        best = None
        for actor, items in by_actor.items():
            buys = [r for r in items if r[3] == "swap" and r[4] == "BUY"]
            lps = [r for r in items if r[3] == "liquidity" and "ADD" in (r[4] or "").upper()]
            for buy in buys:
                bridge = self.db.execute("""
                  SELECT ts,usd,protocol,tx_hash FROM address_events
                  WHERE address=? AND event_type='bridge' AND ts<=? AND ts>=?
                  ORDER BY ts DESC LIMIT 1
                """, (actor, int(buy[1]), int(buy[1]) - self.correlation_window)).fetchone()
                if not bridge:
                    continue
                lp = next((x for x in lps if int(x[1]) >= int(buy[1]) and int(x[1]) - int(buy[1]) <= self.correlation_window), None)
                seq = {
                    "actor": actor,
                    "bridge_ts": int(bridge[0]), "bridge_usd": float(bridge[1] or 0),
                    "bridge_protocol": bridge[2], "bridge_tx": bridge[3],
                    "buy_ts": int(buy[1]), "buy_usd": float(buy[5] or 0), "buy_tx": buy[10],
                    "lp_ts": int(lp[1]) if lp else None,
                    "lp_usd": float(lp[5] or 0) if lp else 0,
                    "lp_tx": lp[10] if lp else None,
                    "complete": bool(lp),
                }
                rank = (1 if lp else 0, seq["bridge_usd"] + seq["buy_usd"] + seq["lp_usd"])
                if best is None or rank > best[0]:
                    best = (rank, seq)
        return best[1] if best else None

    @staticmethod
    def _tier(value, t1, t2, t3, scores=(10, 18, 25)):
        value = float(value or 0)
        if value >= t3: return scores[2]
        if value >= t2: return scores[1]
        if value >= t1: return scores[0]
        return 0

    def analyze_token(self, token, symbol=None):
        token = self.norm(token)
        now = int(time.time())
        cutoff = now - 86400
        rows = self.db.execute("""
          SELECT id,ts,token,event_type,action,usd,actor,pool,protocol,metadata,tx_hash,block_number
          FROM token_events WHERE token=? AND ts>=? ORDER BY ts,id
        """, (token, cutoff)).fetchall()
        if not rows:
            return None

        if not symbol:
            prow = self.db.execute("SELECT symbol FROM token_profiles WHERE token=?", (token,)).fetchone()
            symbol = (prow[0] if prow and prow[0] else None) or token[:10]
        buys = sum(float(r[5] or 0) for r in rows if r[3] == "swap" and r[4] == "BUY")
        sells = sum(float(r[5] or 0) for r in rows if r[3] == "swap" and r[4] == "SELL")
        lp_add = sum(float(r[5] or 0) for r in rows if r[3] == "liquidity" and "ADD" in (r[4] or "").upper())
        lp_remove = sum(float(r[5] or 0) for r in rows if r[3] == "liquidity" and "REMOVE" in (r[4] or "").upper())
        bridge = sum(float(r[5] or 0) for r in rows if r[3] == "bridge")
        actors = sorted({self.norm(r[6]) for r in rows if self.norm(r[6])})
        new_pool = any(bool((json.loads(r[9] or "{}") if r[9] else {}).get("new_pool")) for r in rows if r[3] == "liquidity")

        hot_wallets = 0
        if actors:
            ph = ",".join("?" for _ in actors)
            try:
                hot_wallets = self.db.execute(
                    f"SELECT COUNT(*) FROM address_profiles WHERE address IN ({ph}) AND score>=60", actors
                ).fetchone()[0]
            except Exception:
                hot_wallets = 0

        sequence = self._sequence(token, rows)
        net_buy = buys - sells
        lp_net = lp_add - lp_remove
        pools = sorted({self.norm(r[7]) for r in rows if self.norm(r[7]) and r[3] in {"liquidity", "swap"}})
        lp_drain_ratio = (lp_remove / lp_add) if lp_add > 0 else (1.0 if lp_remove > 0 else 0.0)

        capital = 0
        capital += self._tier(lp_add, 100_000, 250_000, 1_000_000)
        capital += self._tier(max(0, net_buy), 100_000, 250_000, 1_000_000)
        if len(actors) >= 5: capital += 10
        elif len(actors) >= 2: capital += 5
        if hot_wallets >= 3: capital += 15
        elif hot_wallets >= 1: capital += 10
        if new_pool: capital += 10
        if bridge >= 1_000_000: capital += 12
        elif bridge >= 100_000: capital += 6
        if sequence:
            capital += 25 if sequence.get("complete") else 12
        if sells > buys * 1.5 and sells >= self.min_event_usd: capital -= 15
        if lp_remove > lp_add * 0.5 and lp_remove >= self.min_event_usd: capital -= 15
        capital = max(0, min(100, int(capital)))

        previous = self.db.execute("SELECT holders_json,risk_json,last_deep_scan_ts FROM token_profiles WHERE token=?", (token,)).fetchone()
        holders = json.loads(previous[0] or "{}") if previous and previous[0] else {}
        risk = json.loads(previous[1] or "{}") if previous and previous[1] else {}
        last_scan = int(previous[2] or 0) if previous else 0
        if now - last_scan >= self.deep_scan_ttl or not risk:
            try:
                token_obj = self.token_getter(token)
                pool_excludes = {r[7] for r in rows if r[7]}
                deep = self.token_intel.analyze_token(token_obj, pool_excludes)
                holders = deep.get("holders") or {}
                risk = deep.get("risk") or {}
                last_scan = now
            except Exception as e:
                log.warning("deep token scan failed %s: %s", token, e)

        risk_score = int(risk.get("score") or 50)
        risk_penalty = max(0, risk_score - 35) * 0.35
        signal_score = max(0, min(100, int(round(capital - risk_penalty))))

        if ((sequence and sequence.get("complete") and signal_score >= 70 and risk_score <= 70)
                or (signal_score >= 85 and risk_score <= 60)):
            level = "P0"
        elif signal_score >= 65:
            level = "P1"
        elif signal_score >= 45:
            level = "P2"
        else:
            level = "WATCH"

        tags = []
        if new_pool: tags.append("NEW POOL")
        if net_buy >= 1_000_000: tags.append("$1M NET BUY")
        elif net_buy >= 100_000: tags.append("NET BUY")
        if lp_add >= 1_000_000: tags.append("$1M LP")
        elif lp_add >= 100_000: tags.append("LP INFLOW")
        if hot_wallets: tags.append(f"HOT WALLETS {hot_wallets}")
        if sequence: tags.append("BRIDGE→BUY→LP" if sequence.get("complete") else "BRIDGE→BUY")
        if lp_remove >= self.min_event_usd and lp_drain_ratio >= 0.60:
            tags.append("LP OUTFLOW")
        top1 = holders.get("top1")
        top10 = holders.get("top10")
        holder_count = holders.get("holders")
        if top1 is not None and float(top1) >= 30:
            tags.append("TOP1 30%+")
        if top10 is not None and float(top10) >= 70:
            tags.append("TOP10 70%+")
        if holder_count is not None and int(holder_count) < 50:
            tags.append("LOW HOLDERS")
        if risk_score >= 70: tags.append("HIGH RISK")
        elif risk_score <= 30: tags.append("LOWER RISK")

        self.db.execute("""
          UPDATE token_profiles SET symbol=?,last_seen_ts=?,last_seen_block=?,event_count_24h=?,
            buy_usd_24h=?,sell_usd_24h=?,lp_add_usd_24h=?,lp_remove_usd_24h=?,bridge_usd_24h=?,
            unique_wallets_24h=?,hot_wallets_24h=?,pool_count_24h=?,lp_drain_ratio=?,
            capital_score=?,risk_score=?,signal_score=?,signal_level=?,tags=?,holders_json=?,risk_json=?,
            sequence_json=?,last_deep_scan_ts=?,updated_at=?
          WHERE token=?
        """, (symbol, int(rows[-1][1]), int(rows[-1][11] or 0), len(rows), buys, sells, lp_add,
              lp_remove, bridge, len(actors), int(hot_wallets), len(pools), float(lp_drain_ratio),
              capital, risk_score, signal_score, level, json.dumps(tags, ensure_ascii=False), json.dumps(holders, ensure_ascii=False),
              json.dumps(risk, ensure_ascii=False), json.dumps(sequence or {}, ensure_ascii=False),
              last_scan, now, token))
        self.db.commit()

        profile = {
            "token": token, "symbol": symbol, "event_count_24h": len(rows),
            "buy_usd_24h": buys, "sell_usd_24h": sells, "net_buy_usd_24h": net_buy,
            "lp_add_usd_24h": lp_add, "lp_remove_usd_24h": lp_remove, "lp_net_usd_24h": lp_net,
            "bridge_usd_24h": bridge, "unique_wallets_24h": len(actors),
            "hot_wallets_24h": int(hot_wallets), "pool_count_24h": len(pools),
            "lp_drain_ratio": float(lp_drain_ratio), "capital_score": capital,
            "risk_score": risk_score, "signal_score": signal_score, "signal_level": level,
            "tags": tags, "holders": holders, "risk": risk, "sequence": sequence or {},
        }
        self._maybe_signal(profile)
        return profile

    def _maybe_signal(self, p):
        level = p["signal_level"]
        if level not in {"P0", "P1"} or p["signal_score"] < self.signal_min_score:
            return
        now = int(time.time())
        seq = p.get("sequence") or {}
        sig_type = "BRIDGE_BUY_LP" if seq.get("complete") else "TOKEN_MOMENTUM"
        # Real cooldown instead of clock buckets: avoids duplicate alerts one
        # minute apart when an event lands on a half-hour boundary. P0 may
        # escalate immediately from P1, while P1 is suppressed after any recent
        # P0/P1 signal for the same token/type.
        if level == "P0":
            last = self.db.execute("""SELECT ts FROM token_signals
                                      WHERE token=? AND signal_type=? AND level='P0'
                                      ORDER BY ts DESC LIMIT 1""",
                                   (p["token"], sig_type)).fetchone()
        else:
            last = self.db.execute("""SELECT ts FROM token_signals
                                      WHERE token=? AND signal_type=? AND level IN ('P0','P1')
                                      ORDER BY ts DESC LIMIT 1""",
                                   (p["token"], sig_type)).fetchone()
        if last and now - int(last[0]) < self.signal_cooldown:
            return
        key = f"token:{p['token']}:{sig_type}:{level}:{now}"
        details = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
        self.db.execute("""
          INSERT INTO token_signals(signal_key,ts,token,symbol,level,signal_type,score,risk_score,details)
          VALUES(?,?,?,?,?,?,?,?,?)
        """, (key, now, p["token"], p["symbol"], level, sig_type,
              p["signal_score"], p["risk_score"], details))
        self.db.commit()

        holders = p.get("holders") or {}
        risk = p.get("risk") or {}
        if self.zh:
            seq_line = ""
            if seq:
                seq_line = (f"\n资金路径：跨链 ${seq.get('bridge_usd',0):,.0f} → 买入 ${seq.get('buy_usd',0):,.0f}"
                            + (f" → 加池 ${seq.get('lp_usd',0):,.0f}" if seq.get("complete") else ""))
            text = (
                f"🛰 {level} · Token 早期资金雷达\n"
                f"代币：{p['symbol']}\nCA：{p['token']}\n"
                f"信号分：{p['signal_score']}/100 · 资金分：{p['capital_score']}/100 · 风险分：{p['risk_score']}/100\n"
                f"24h 大额买入：${p['buy_usd_24h']:,.0f} · 卖出：${p['sell_usd_24h']:,.0f} · 净买入：${p['net_buy_usd_24h']:,.0f}\n"
                f"24h LP：加 ${p['lp_add_usd_24h']:,.0f} · 撤 ${p['lp_remove_usd_24h']:,.0f} · 净 ${p['lp_net_usd_24h']:,.0f} · 池 {p.get('pool_count_24h',0)}\n"
                f"活跃地址：{p['unique_wallets_24h']} · 高分地址：{p['hot_wallets_24h']}\n"
                f"持有人：{holders.get('holders','未知')} · Top1：{self._pct(holders.get('top1'))} · Top10：{self._pct(holders.get('top10'))}"
                f"{seq_line}\n"
                f"风险：{risk.get('level','未知')} · {'、'.join((risk.get('flags') or [])[:4]) or '暂无明显权限命中'}\n"
                f"合约：{self.explorer}/address/{p['token']}\n"
                "说明：这是链上资金与权限启发式观察信号，不构成买卖建议。"
            )
        else:
            seq_line = ""
            if seq:
                seq_line = (f"\nFlow: bridge ${seq.get('bridge_usd',0):,.0f} → buy ${seq.get('buy_usd',0):,.0f}"
                            + (f" → LP ${seq.get('lp_usd',0):,.0f}" if seq.get("complete") else ""))
            text = (
                f"🛰 {level} · Token Early-Capital Radar\n"
                f"Token: {p['symbol']}\nCA: {p['token']}\n"
                f"Signal: {p['signal_score']}/100 · Capital: {p['capital_score']}/100 · Risk: {p['risk_score']}/100\n"
                f"24h large buys: ${p['buy_usd_24h']:,.0f} · sells: ${p['sell_usd_24h']:,.0f} · net: ${p['net_buy_usd_24h']:,.0f}\n"
                f"24h LP: add ${p['lp_add_usd_24h']:,.0f} · remove ${p['lp_remove_usd_24h']:,.0f} · net ${p['lp_net_usd_24h']:,.0f} · pools {p.get('pool_count_24h',0)}\n"
                f"Active wallets: {p['unique_wallets_24h']} · high-score wallets: {p['hot_wallets_24h']}\n"
                f"Holders: {holders.get('holders','Unknown')} · Top1: {self._pct(holders.get('top1'))} · Top10: {self._pct(holders.get('top10'))}"
                f"{seq_line}\n"
                f"Risk: {risk.get('level_en') or risk.get('level','Unknown')} · {', '.join((risk.get('flags_en') or risk.get('flags') or [])[:4]) or 'no common permission flags'}\n"
                f"Contract: {self.explorer}/address/{p['token']}\n"
                "Note: this is an on-chain capital/permission heuristic, not trading advice."
            )

        self.save_alert(level, "token-signal", "Token Radar", sig_type,
                        p["net_buy_usd_24h"], p["symbol"], p["token"], "", 0,
                        f"signal={p['signal_score']}; capital={p['capital_score']}; risk={p['risk_score']}")
        self.telegram(text[:3500])

    @staticmethod
    def _pct(v):
        try:
            return f"{float(v):.1f}%"
        except Exception:
            return "—"

    def run_worker(self, stop_event=None):
        # Recover interrupted work after process restart.
        try:
            self.db.execute("UPDATE token_scan_queue SET status=0,claimed_at=NULL WHERE status=1")
            self.db.commit()
        except Exception:
            pass
        while stop_event is None or not stop_event.is_set():
            item = None
            try:
                # Heartbeat must advance even while the queue is empty so the
                # Dashboard reports worker liveness rather than event activity.
                self.db.execute("INSERT OR REPLACE INTO kv(k,v) VALUES('token_radar_heartbeat',?)",
                                (str(int(time.time())),))
                self.db.commit()
                item = self._claim()
                if not item:
                    if stop_event is not None:
                        stop_event.wait(0.5)
                    else:
                        time.sleep(0.5)
                    continue
                token, symbol, queued_at, claimed_at = item
                self.analyze_token(token, symbol)
                self._queue_done(token, queued_at)
            except Exception as e:
                log.exception("token radar worker error")
                if item:
                    try:
                        self._queue_error(item[0], e)
                    except Exception:
                        pass
                if stop_event is not None:
                    stop_event.wait(1)
                else:
                    time.sleep(1)

#!/usr/bin/env python3
import json
import time
from collections import OrderedDict

ZERO = "0x0000000000000000000000000000000000000000"

class AddressIntel:
    """Address-centric capital-flow intelligence for Robinhood Chain Radar."""
    def __init__(
        self, db, rpc, telegram, save_alert, explorer,
        correlation_window_min=60,
        fresh_wallet_max_tx_count=3,
        bridge_min_usd=100_000,
        lp_min_usd=100_000,
        swap_min_usd=100_000,
        p0_bridge_usd=1_000_000,
        p0_lp_usd=1_000_000,
        language="zh_CN",
    ):
        self.db = db
        self.rpc = rpc
        self.telegram = telegram
        self.save_alert = save_alert
        self.explorer = explorer.rstrip("/")
        self.window = int(correlation_window_min) * 60
        self.fresh_max = int(fresh_wallet_max_tx_count)
        self.bridge_min = float(bridge_min_usd)
        self.lp_min = float(lp_min_usd)
        self.swap_min = float(swap_min_usd)
        self.p0_bridge = float(p0_bridge_usd)
        self.p0_lp = float(p0_lp_usd)
        self.language = language or "zh_CN"
        self.tx_cache = OrderedDict()
        self.tx_cache_max = 2048
        self._ensure_schema()

    def _ensure_schema(self):
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS address_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts INTEGER NOT NULL,
          address TEXT NOT NULL,
          event_type TEXT NOT NULL,
          protocol TEXT NOT NULL,
          action TEXT NOT NULL,
          usd REAL,
          token_pair TEXT,
          subject TEXT,
          tx_hash TEXT,
          block_number INTEGER,
          metadata TEXT
        )
        """)
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS address_profiles (
          address TEXT PRIMARY KEY,
          first_seen_ts INTEGER NOT NULL,
          last_seen_ts INTEGER NOT NULL,
          first_seen_block INTEGER,
          last_seen_block INTEGER,
          first_tx_count INTEGER,
          is_fresh INTEGER NOT NULL DEFAULT 0,
          score INTEGER NOT NULL DEFAULT 0,
          tags TEXT NOT NULL DEFAULT '[]',
          bridge_usd_24h REAL NOT NULL DEFAULT 0,
          lp_usd_24h REAL NOT NULL DEFAULT 0,
          swap_usd_24h REAL NOT NULL DEFAULT 0,
          event_count_24h INTEGER NOT NULL DEFAULT 0
        )
        """)
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS amm_pools (
          pool_key TEXT PRIMARY KEY,
          version TEXT NOT NULL,
          token0 TEXT,
          token1 TEXT,
          created_block INTEGER,
          created_tx TEXT
        )
        """)
        self.db.execute("""
        CREATE TABLE IF NOT EXISTS intel_signals (
          signal_key TEXT PRIMARY KEY,
          ts INTEGER NOT NULL,
          address TEXT NOT NULL,
          signal_type TEXT NOT NULL,
          score INTEGER NOT NULL,
          details TEXT
        )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_addr_events_addr_ts ON address_events(address,ts DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_addr_events_ts ON address_events(ts DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_addr_events_type_ts ON address_events(event_type,ts DESC)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_profiles_score ON address_profiles(score DESC,last_seen_ts DESC)")
        self.db.commit()

    @staticmethod
    def norm(addr):
        return (addr or "").lower()

    def _cache_put(self, key, value):
        self.tx_cache[key] = value
        self.tx_cache.move_to_end(key)
        while len(self.tx_cache) > self.tx_cache_max:
            self.tx_cache.popitem(last=False)

    def tx(self, tx_hash):
        if not tx_hash:
            return None
        if tx_hash in self.tx_cache:
            return self.tx_cache[tx_hash]
        try:
            tx = self.rpc.call("eth_getTransactionByHash", [tx_hash], timeout=15)
        except Exception:
            tx = None
        self._cache_put(tx_hash, tx)
        return tx

    def actor_for_tx(self, tx_hash, fallback=None):
        tx = self.tx(tx_hash)
        actor = self.norm((tx or {}).get("from"))
        return actor if actor else self.norm(fallback)

    def tx_count_at(self, address, block_number):
        a = self.norm(address)
        if not a or a == ZERO:
            return None
        tag = hex(int(block_number)) if block_number else "latest"
        try:
            raw = self.rpc.call("eth_getTransactionCount", [a, tag], timeout=12)
            return int(raw, 16)
        except Exception:
            return None

    def register_pool(self, pool_key, version, token0=None, token1=None, block_number=0, tx_hash=None):
        p = self.norm(pool_key)
        if not p:
            return
        self.db.execute("""
          INSERT OR REPLACE INTO amm_pools(pool_key,version,token0,token1,created_block,created_tx)
          VALUES(?,?,?,?,?,?)
        """, (p, str(version), self.norm(token0), self.norm(token1), int(block_number or 0), tx_hash))
        self.db.commit()

    def pool_is_new(self, pool_key, current_block, within_blocks=1000):
        row = self.db.execute("SELECT created_block FROM amm_pools WHERE pool_key=?", (self.norm(pool_key),)).fetchone()
        if not row or not row[0]:
            return False
        return 0 <= int(current_block) - int(row[0]) <= int(within_blocks)

    def _ensure_profile(self, address, block_number):
        a = self.norm(address)
        now = int(time.time())
        row = self.db.execute("SELECT address FROM address_profiles WHERE address=?", (a,)).fetchone()
        if row:
            return
        tx_count = self.tx_count_at(a, block_number)
        is_fresh = 1 if tx_count is not None and tx_count <= self.fresh_max else 0
        self.db.execute("""
          INSERT INTO address_profiles(
            address,first_seen_ts,last_seen_ts,first_seen_block,last_seen_block,
            first_tx_count,is_fresh,score,tags
          ) VALUES(?,?,?,?,?,?,?,?,?)
        """, (a, now, now, int(block_number or 0), int(block_number or 0), tx_count, is_fresh, 0,
              json.dumps(["FRESH"] if is_fresh else [])))
        self.db.commit()

    def record(self, address, event_type, protocol, action, usd=None, token_pair="",
               subject="", tx_hash="", block_number=0, metadata=None):
        a = self.norm(address)
        if not a or a == ZERO:
            return None
        usd_f = float(usd or 0)
        min_required = {"bridge": self.bridge_min, "liquidity": self.lp_min, "swap": self.swap_min}.get(event_type, 0)
        if usd is not None and usd_f < min_required:
            return None

        self._ensure_profile(a, block_number)
        now = int(time.time())
        dedupe = self.db.execute("""
          SELECT id FROM address_events
          WHERE address=? AND event_type=? AND tx_hash=? AND action=? AND subject=? LIMIT 1
        """, (a, event_type, tx_hash, action, subject)).fetchone()
        if dedupe:
            return dedupe[0]

        cur = self.db.execute("""
          INSERT INTO address_events(
            ts,address,event_type,protocol,action,usd,token_pair,subject,tx_hash,block_number,metadata
          ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (now, a, event_type, protocol, action, usd_f if usd is not None else None,
              token_pair, subject, tx_hash, int(block_number or 0),
              json.dumps(dict(metadata or {}), ensure_ascii=False, separators=(",", ":"))))
        self.db.execute("UPDATE address_profiles SET last_seen_ts=?,last_seen_block=? WHERE address=?",
                        (now, int(block_number or 0), a))
        self.db.commit()
        score, _ = self.refresh_profile(a)
        if event_type == "liquidity" and "ADD" in action.upper():
            self._check_capital_deployment(a, cur.lastrowid, score)
        return cur.lastrowid

    def refresh_profile(self, address):
        a = self.norm(address)
        now = int(time.time())
        rows = self.db.execute("""
          SELECT ts,event_type,action,usd,metadata,tx_hash,token_pair,subject
          FROM address_events WHERE address=? AND ts>=? ORDER BY ts ASC,id ASC
        """, (a, now - 86400)).fetchall()
        profile = self.db.execute("SELECT is_fresh FROM address_profiles WHERE address=?", (a,)).fetchone()
        is_fresh = bool(profile and profile[0])

        bridge = sum(float(r[3] or 0) for r in rows if r[1] == "bridge")
        lp_add = sum(float(r[3] or 0) for r in rows if r[1] == "liquidity" and "ADD" in (r[2] or "").upper())
        swap = sum(float(r[3] or 0) for r in rows if r[1] == "swap")
        has_bridge_m = any(r[1] == "bridge" and float(r[3] or 0) >= self.p0_bridge for r in rows)
        has_lp_m = any(r[1] == "liquidity" and "ADD" in (r[2] or "").upper() and float(r[3] or 0) >= self.p0_lp for r in rows)
        has_swap = any(r[1] == "swap" and float(r[3] or 0) >= self.swap_min for r in rows)
        new_pool = False
        for r in rows:
            if r[1] == "liquidity":
                try:
                    if json.loads(r[4] or "{}").get("new_pool"):
                        new_pool = True
                        break
                except Exception:
                    pass

        bridge_times = [r[0] for r in rows if r[1] == "bridge" and float(r[3] or 0) >= self.p0_bridge]
        correlated = any(
            r[1] == "liquidity" and "ADD" in (r[2] or "").upper() and float(r[3] or 0) >= self.p0_lp
            and any(0 <= r[0] - bt <= self.window for bt in bridge_times)
            for r in rows
        )

        score = 0
        if is_fresh: score += 15
        if has_bridge_m: score += 30
        elif bridge >= self.bridge_min: score += 12
        if has_lp_m: score += 20
        elif lp_add >= self.lp_min: score += 8
        if has_swap: score += 8
        if new_pool: score += 10
        if correlated: score += 30
        if len(rows) >= 4: score += 5
        score = min(100, score)

        tags = []
        if is_fresh: tags.append("FRESH")
        if has_bridge_m: tags.append("WHALE BRIDGE")
        if has_swap: tags.append("ACTIVE SWAP")
        if has_lp_m: tags.append("LP DEPLOY")
        if new_pool: tags.append("NEW POOL")
        if correlated: tags.append("BRIDGE→LP")
        if score >= 80: tags.insert(0, "HOT")

        self.db.execute("""
          UPDATE address_profiles
          SET score=?,tags=?,bridge_usd_24h=?,lp_usd_24h=?,swap_usd_24h=?,event_count_24h=?
          WHERE address=?
        """, (score, json.dumps(tags, ensure_ascii=False), bridge, lp_add, swap, len(rows), a))
        self.db.commit()
        return score, tags

    def _check_capital_deployment(self, address, lp_event_id, score):
        lp = self.db.execute("""
          SELECT id,ts,usd,protocol,action,token_pair,subject,tx_hash,block_number,metadata
          FROM address_events WHERE id=?
        """, (lp_event_id,)).fetchone()
        if not lp or float(lp[2] or 0) < self.p0_lp:
            return
        bridge = self.db.execute("""
          SELECT id,ts,usd,protocol,token_pair,subject,tx_hash,block_number
          FROM address_events
          WHERE address=? AND event_type='bridge' AND usd>=? AND ts<=? AND ts>=?
          ORDER BY ts DESC LIMIT 1
        """, (address, self.p0_bridge, lp[1], lp[1] - self.window)).fetchone()
        if not bridge:
            return

        signal_key = f"deploy:{address}:{bridge[0]}:{lp[0]}"
        if self.db.execute("SELECT 1 FROM intel_signals WHERE signal_key=?", (signal_key,)).fetchone():
            return
        swaps = self.db.execute("""
          SELECT COUNT(*),COALESCE(SUM(usd),0) FROM address_events
          WHERE address=? AND event_type='swap' AND ts>=? AND ts<=?
        """, (address, bridge[1], lp[1])).fetchone()
        swap_count, swap_usd = int(swaps[0]), float(swaps[1] or 0)
        mins = max(0, int((lp[1] - bridge[1]) / 60))
        details = {
            "bridge_usd": float(bridge[2] or 0), "bridge_protocol": bridge[3],
            "lp_usd": float(lp[2] or 0), "lp_protocol": lp[3], "pair": lp[5],
            "minutes": mins, "swap_count_between": swap_count, "swap_usd_between": swap_usd,
        }
        self.db.execute("""
          INSERT INTO intel_signals(signal_key,ts,address,signal_type,score,details)
          VALUES(?,?,?,?,?,?)
        """, (signal_key, int(time.time()), address, "CAPITAL_DEPLOYMENT", int(score),
              json.dumps(details, ensure_ascii=False)))
        self.db.commit()

        if self.language.lower().startswith("zh"):
            swap_line = f"期间大额 Swap：{swap_count} 笔 · ${swap_usd:,.0f}\n" if swap_count else ""
            text = (
                "🚨 P0 · Robinhood 链资金部署强信号\n"
                f"钱包：{address}\n资金评分：{score}/100\n"
                f"跨链流入：${float(bridge[2]):,.0f} · {bridge[3]}\n"
                f"随后加池：${float(lp[2]):,.0f} · {lp[3]}\n交易对：{lp[5] or '—'}\n"
                f"间隔：{mins} 分钟\n{swap_line}"
                f"钱包详情：{self.explorer}/address/{address}\nLP 交易：{self.explorer}/tx/{lp[7]}"
            )
        else:
            swap_line = f"Interim large swaps: {swap_count} · ${swap_usd:,.0f}\n" if swap_count else ""
            text = (
                "🚨 P0 · Robinhood Capital Deployment Signal\n"
                f"Wallet: {address}\nCapital score: {score}/100\n"
                f"Bridge in: ${float(bridge[2]):,.0f} · {bridge[3]}\n"
                f"Then LP: ${float(lp[2]):,.0f} · {lp[3]}\nPair: {lp[5] or '—'}\n"
                f"Delay: {mins} min\n{swap_line}"
                f"Wallet: {self.explorer}/address/{address}\nLP Tx: {self.explorer}/tx/{lp[7]}"
            )
        self.save_alert(
            "P0", "signal", "Capital Radar", "BRIDGE→LP", float(lp[2] or 0), lp[5] or "",
            address, lp[7], int(lp[8] or 0),
            f"score={score}; bridge=${float(bridge[2]):.0f}; delay={mins}m; swaps={swap_count}"
        )
        self.telegram(text)

#!/usr/bin/env python3
import sqlite3
import threading
import time
from token_intel import TokenIntelligence, ZERO
from token_radar import TokenRadar


class T:
    def __init__(self, a, s, d=18):
        self.address = a; self.symbol = s; self.decimals = d


class FakeRPC:
    def eth_call(self, to, data, block="latest"):
        if data == "0x18160ddd":
            return hex(1_000_000 * 10**18)
        if data == "0x8da5cb5b":
            return "0x" + "00" * 32
        raise RuntimeError("offline")


class FakeDB:
    def execute(self, *a, **k):
        class R:
            def fetchall(self): return []
        return R()


weth = "0x" + "11" * 20
usdg = "0x" + "22" * 20
mow = "0x" + "44" * 20
intel = TokenIntelligence(FakeRPC(), FakeDB(), "https://example", weth, usdg, "0x" + "33" * 20)
t0, t1 = T(weth, "WETH"), T(mow, "MOW")
focus, other = intel._pick_focus(t0, t1)
assert focus.symbol == "MOW"
assert intel._fmt_pct(12.345) == "12.3%"
assert intel._fmt_money(1_016_000) == "$1.02M"
# V4 fee formatting regression: 3000 = 0.3%, never "%%".
intel._holder_stats = lambda token, excludes: {"holders": 100, "top1": 5.0, "top10": 20.0, "burn": 0.0}
intel._contract_risk = lambda token: {"level": "较低", "verified": True, "proxy": False, "owner": None, "flags": [], "note": "ok"}
intel._lp_activity = lambda subject: (0.0, 0.0, 0, 0)
report = intel.build_liquidity_report("v4", "0x"+"77"*32, 1_000_000, t0, t1, 1,
                                      v4_meta={"fee": 3000, "tick_spacing": 60, "hooks": ZERO})
assert "0.3%" in report and "%%" not in report

# V1.3 token radar offline smoke test.
db = sqlite3.connect(":memory:", check_same_thread=False)
db.execute("CREATE TABLE kv(k TEXT PRIMARY KEY,v TEXT NOT NULL)")
db.execute("CREATE TABLE address_profiles(address TEXT PRIMARY KEY,score INTEGER)")
db.execute("""CREATE TABLE address_events(
    id INTEGER PRIMARY KEY,ts INTEGER,address TEXT,event_type TEXT,protocol TEXT,
    action TEXT,usd REAL,token_pair TEXT,subject TEXT,tx_hash TEXT,block_number INTEGER,metadata TEXT
)""")

class FakeDeepIntel:
    def analyze_token(self, token, exclude_addrs=None):
        return {
            "holders": {"holders": 123, "top1": 8.0, "top10": 31.0, "burn": 0.0},
            "risk": {"score": 20, "level": "较低", "level_en": "Lower", "flags": [], "flags_en": []},
        }


def get_token(addr):
    return T(addr, "MOW")

radar = TokenRadar(db, FakeDeepIntel(), get_token, lambda _: None, lambda *a: None,
                   "https://example", weth, usdg, min_event_usd=0, signal_min_score=101)
actor = "0x" + "55" * 20
pool = "0x" + "66" * 20
now = int(time.time())
db.execute("INSERT INTO address_profiles(address,score) VALUES(?,?)", (actor, 80))
db.execute("""INSERT INTO address_events(id,ts,address,event_type,protocol,action,usd,token_pair,subject,tx_hash,block_number,metadata)
              VALUES(1,?,?,?,?,?,?,?,?,?,?,?)""",
           (now-60, actor, "bridge", "Canonical", "BRIDGE IN", 1_200_000, "ETH", actor, "0xbridge", 99, "{}"))
radar.observe_swap("v2", pool, 300_000, t0, t1, 10**18, -(10**18), actor, "0xaaa", 100)
radar.observe_liquidity("v2", "NEW POOL ADD", pool, 1_100_000, t0, t1, actor, "0xbbb", 101, new_pool=True)
p = radar.analyze_token(mow, "MOW")
assert p["buy_usd_24h"] == 300_000
assert p["lp_add_usd_24h"] == 1_100_000
assert p["risk_score"] == 20
assert "NEW POOL" in p["tags"]
assert p["pool_count_24h"] == 1
assert p["sequence"].get("complete") is True
assert p["signal_level"] == "P0"
q = db.execute("SELECT priority FROM token_scan_queue WHERE token=?", (mow,)).fetchone()
assert q and int(q[0]) >= 80

# Non-base token/token pools must create a radar profile for both sides.
a = T("0x" + "77" * 20, "AAA")
b = T("0x" + "88" * 20, "BBB")
radar.observe_swap("v3", "0x"+"99"*20, 200_000, a, b, 5, -7, actor, "0xdual", 102)
assert db.execute("SELECT action FROM token_events WHERE token=? AND tx_hash='0xdual'", (a.address,)).fetchone()[0] == "SELL"
assert db.execute("SELECT action FROM token_events WHERE token=? AND tx_hash='0xdual'", (b.address,)).fetchone()[0] == "BUY"

# LP outflow/concentration flags are intentionally visible, not hidden by a high capital score.
class RiskyDeepIntel:
    def analyze_token(self, token, exclude_addrs=None):
        return {
            "holders": {"holders": 20, "top1": 35.0, "top10": 82.0, "burn": 0.0},
            "risk": {"score": 78, "level": "高", "level_en": "High", "flags": ["Owner 仍存在"], "flags_en": ["Owner still active"]},
        }

risky_ca = "0x" + "99" * 20
risky = T(risky_ca, "RISK")
r2 = TokenRadar(db, RiskyDeepIntel(), lambda a: risky, lambda _: None, lambda *a: None,
                "https://example", weth, usdg, min_event_usd=0, signal_min_score=101)
r2.observe_liquidity("v2", "ADD", "0x"+"ab"*20, 200_000, t0, risky, actor, "0xadd", 103)
r2.observe_liquidity("v2", "REMOVE", "0x"+"ab"*20, 150_000, t0, risky, actor, "0xremove", 104)
rp = r2.analyze_token(risky_ca, "RISK")
for tag in ("LP OUTFLOW", "TOP1 30%+", "TOP10 70%+", "LOW HOLDERS", "HIGH RISK"):
    assert tag in rp["tags"], (tag, rp["tags"])

# An idle Token Radar worker must still emit a heartbeat. The Dashboard should
# report worker liveness, not whether a token happened to arrive recently.
idle_db = sqlite3.connect(":memory:", check_same_thread=False)
idle_db.execute("CREATE TABLE kv(k TEXT PRIMARY KEY,v TEXT NOT NULL)")
idle_db.execute("CREATE TABLE address_profiles(address TEXT PRIMARY KEY,score INTEGER)")
idle_db.execute("""CREATE TABLE address_events(
    id INTEGER PRIMARY KEY,ts INTEGER,address TEXT,event_type TEXT,protocol TEXT,
    action TEXT,usd REAL,token_pair TEXT,subject TEXT,tx_hash TEXT,block_number INTEGER,metadata TEXT
)""")
idle = TokenRadar(idle_db, FakeDeepIntel(), get_token, lambda _: None, lambda *a: None,
                  "https://example", weth, usdg, min_event_usd=0, signal_min_score=101)
stop = threading.Event()
th = threading.Thread(target=idle.run_worker, args=(stop,), daemon=True)
th.start(); time.sleep(0.08); stop.set(); th.join(1)
hb = idle_db.execute("SELECT v FROM kv WHERE k='token_radar_heartbeat'").fetchone()
assert hb and int(hb[0]) > 0

print("static smoke test: OK (V1.3.0 token radar + BUY/SELL + LP + risk + idle heartbeat)")

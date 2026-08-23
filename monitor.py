#!/usr/bin/env python3
import os
import sys
import time
import json
import math
import sqlite3
import logging
import threading
from collections import deque
from pathlib import Path
from address_intel import AddressIntel
from token_intel import TokenIntelligence
from token_radar import TokenRadar
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List

import requests


def load_dotenv(path=None):
    """Tiny .env loader to keep Termux dependencies minimal."""
    p = Path(path) if path else Path(__file__).with_name(".env")
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)

# Keccak-256 (Ethereum variant), implemented in pure Python.
# This avoids eth-utils / pydantic / Rust build dependencies on Android Termux.
_KECCAK_RC = [
    0x0000000000000001,0x0000000000008082,0x800000000000808A,0x8000000080008000,
    0x000000000000808B,0x0000000080000001,0x8000000080008081,0x8000000000008009,
    0x000000000000008A,0x0000000000000088,0x0000000080008009,0x000000008000000A,
    0x000000008000808B,0x800000000000008B,0x8000000000008089,0x8000000000008003,
    0x8000000000008002,0x8000000000000080,0x000000000000800A,0x800000008000000A,
    0x8000000080008081,0x8000000000008080,0x0000000080000001,0x8000000080008008,
]
_KECCAK_ROT = [
    [0,36,3,41,18],
    [1,44,10,45,2],
    [62,6,43,15,61],
    [28,55,25,21,56],
    [27,20,39,8,14],
]
_MASK64 = (1 << 64) - 1

def _rol64(v, n):
    if n == 0:
        return v & _MASK64
    return ((v << n) | (v >> (64 - n))) & _MASK64

def _keccak_f(state):
    a = state[:]
    for rc in _KECCAK_RC:
        c = [a[x] ^ a[x+5] ^ a[x+10] ^ a[x+15] ^ a[x+20] for x in range(5)]
        d = [c[(x-1) % 5] ^ _rol64(c[(x+1) % 5], 1) for x in range(5)]
        for y in range(5):
            for x in range(5):
                a[x + 5*y] ^= d[x]

        b = [0] * 25
        for y in range(5):
            for x in range(5):
                b[y + 5*((2*x + 3*y) % 5)] = _rol64(a[x + 5*y], _KECCAK_ROT[x][y])

        for y in range(5):
            for x in range(5):
                a[x + 5*y] = (
                    b[x + 5*y]
                    ^ ((~b[(x+1) % 5 + 5*y]) & b[(x+2) % 5 + 5*y])
                ) & _MASK64
        a[0] ^= rc
    return a

def keccak256(data: bytes) -> bytes:
    rate = 136  # Keccak-256 rate in bytes
    padded = bytearray(data)
    padded.append(0x01)  # Keccak domain suffix, not SHA3's 0x06
    while len(padded) % rate != rate - 1:
        padded.append(0)
    padded.append(0x80)

    state = [0] * 25
    for off in range(0, len(padded), rate):
        block = padded[off:off+rate]
        for i in range(rate // 8):
            state[i] ^= int.from_bytes(block[i*8:(i+1)*8], "little")
        state = _keccak_f(state)

    out = bytearray()
    while len(out) < 32:
        for i in range(rate // 8):
            out.extend(state[i].to_bytes(8, "little"))
            if len(out) >= 32:
                break
        if len(out) < 32:
            state = _keccak_f(state)
    return bytes(out[:32])

def keccak_text(text: str) -> bytes:
    return keccak256(text.encode("utf-8"))

load_dotenv()

# ----------------------------
# Network / protocol constants
# ----------------------------
CHAIN_ID = 4663
DEFAULT_RPC = "https://rpc.mainnet.chain.robinhood.com"
EXPLORER = "https://robinhoodchain.blockscout.com"

# Official Uniswap deployments for Robinhood Chain (chain 4663)
UNISWAP_V2_FACTORY_DEFAULT = "0x8bceaa40b9acdfaedf85adf4ff01f5ad6517937f"
UNISWAP_V3_FACTORY_DEFAULT = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
UNISWAP_V4_POOL_MANAGER_DEFAULT = "0x8366a39cc670b4001a1121b8f6a443a643e40951"

# Official Robinhood canonical L2 gateways
L2_GATEWAY_ROUTER_DEFAULT = "0x1e324b9316138ca9a73f960213621ad1aaf01b89"
L2_ERC20_GATEWAY_DEFAULT = "0xfd9b17206278c16ddaacf6ac8f05dbf97edcb31e"
L2_CUSTOM_GATEWAY_DEFAULT = "0x912285144fc0f6e89d3ed16f5ab72f87a1878959"
L2_WETH_GATEWAY_DEFAULT = "0x1d187c3e2da52d72bc9c41e3aba0fdfa6a7bf055"

WETH_DEFAULT = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
USDG_DEFAULT = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"

# Common selectors
SEL_FACTORY = "0xc45a0155"          # factory()
SEL_TOKEN0 = "0x0dfe1681"           # token0()
SEL_TOKEN1 = "0xd21220a7"           # token1()
SEL_SYMBOL = "0x95d89b41"           # symbol()
SEL_DECIMALS = "0x313ce567"         # decimals()
SEL_SLOT0 = "0x3850c7bd"            # slot0()
SEL_GET_RESERVES = "0x0902f1ac"      # getReserves()
SEL_CALC_L2 = "0x" + keccak_text("calculateL2TokenAddress(address)")[:4].hex()
SEL_V4_GET_SLOT0 = "0x" + keccak_text("getSlot0(bytes32)")[:4].hex()

# Event topics
TOPIC_V2_MINT = "0x" + keccak_text("Mint(address,uint256,uint256)").hex()
TOPIC_V2_BURN = "0x" + keccak_text("Burn(address,uint256,uint256,address)").hex()
TOPIC_V2_PAIR_CREATED = "0x" + keccak_text("PairCreated(address,address,address,uint256)").hex()

TOPIC_V3_MINT = "0x" + keccak_text("Mint(address,address,int24,int24,uint128,uint256,uint256)").hex()
TOPIC_V3_BURN = "0x" + keccak_text("Burn(address,int24,int24,uint128,uint256,uint256)").hex()
TOPIC_V3_POOL_CREATED = "0x" + keccak_text("PoolCreated(address,address,uint24,int24,address)").hex()

TOPIC_DEPOSIT_FINALIZED = "0x" + keccak_text("DepositFinalized(address,address,address,uint256)").hex()
TOPIC_V4_INITIALIZE = "0x" + keccak_text("Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)").hex()
TOPIC_V4_MODIFY_LIQUIDITY = "0x" + keccak_text("ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)").hex()
TOPIC_V2_SWAP = "0x" + keccak_text("Swap(address,uint256,uint256,uint256,uint256,address)").hex()
TOPIC_V3_SWAP = "0x" + keccak_text("Swap(address,address,int256,int256,uint160,uint128,int24)").hex()
TOPIC_V4_SWAP = "0x" + keccak_text("Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)").hex()

# ----------------------------
# Config
# ----------------------------
RPC_URL = os.getenv("RH_RPC_URL", DEFAULT_RPC).strip()
V2_FACTORY = os.getenv("UNISWAP_V2_FACTORY", UNISWAP_V2_FACTORY_DEFAULT).lower()
V3_FACTORY = os.getenv("UNISWAP_V3_FACTORY", UNISWAP_V3_FACTORY_DEFAULT).lower()
V4_POOL_MANAGER = os.getenv("UNISWAP_V4_POOL_MANAGER", UNISWAP_V4_POOL_MANAGER_DEFAULT).lower()
V4_STATE_VIEW = os.getenv("UNISWAP_V4_STATE_VIEW", "0xf3334192d15450cdd385c8b70e03f9a6bd9e673b").lower()
V4_POSITION_MANAGER = os.getenv("UNISWAP_V4_POSITION_MANAGER", "0x58daec3116aae6d93017baaea7749052e8a04fa7").lower()

L2_GATEWAY_ROUTER = os.getenv("L2_GATEWAY_ROUTER", L2_GATEWAY_ROUTER_DEFAULT).lower()
L2_ERC20_GATEWAY = os.getenv("L2_ERC20_GATEWAY", L2_ERC20_GATEWAY_DEFAULT).lower()
L2_CUSTOM_GATEWAY = os.getenv("L2_CUSTOM_GATEWAY", L2_CUSTOM_GATEWAY_DEFAULT).lower()
L2_WETH_GATEWAY = os.getenv("L2_WETH_GATEWAY", L2_WETH_GATEWAY_DEFAULT).lower()

WETH = os.getenv("WETH_ADDRESS", WETH_DEFAULT).lower()
USDG = os.getenv("USDG_ADDRESS", USDG_DEFAULT).lower()

LANGUAGE = os.getenv("LANGUAGE", "zh_CN").strip() or "zh_CN"

def tr(zh: str, en: str) -> str:
    return zh if LANGUAGE.lower().startswith("zh") else en

ALERT_USD = float(os.getenv("ALERT_USD", "1000000"))
CUM_ALERT_USD = float(os.getenv("CUM_ALERT_USD", "1000000"))
CUM_WINDOW_SECONDS = int(os.getenv("CUM_WINDOW_MIN", "10")) * 60
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "2"))
BLOCK_CHUNK = int(os.getenv("BLOCK_CHUNK", "50"))
START_BACKFILL_BLOCKS = int(os.getenv("START_BACKFILL_BLOCKS", "20"))
CONFIRMATIONS = int(os.getenv("CONFIRMATIONS", "0"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

RADAR_VERSION = "1.3.0"
INTEL_CORRELATION_WINDOW_MIN = int(os.getenv("INTEL_CORRELATION_WINDOW_MIN", "60"))
FRESH_WALLET_MAX_TX_COUNT = int(os.getenv("FRESH_WALLET_MAX_TX_COUNT", "3"))
INTEL_BRIDGE_MIN_USD = float(os.getenv("INTEL_BRIDGE_MIN_USD", "100000"))
INTEL_LP_MIN_USD = float(os.getenv("INTEL_LP_MIN_USD", "100000"))
INTEL_SWAP_MIN_USD = float(os.getenv("INTEL_SWAP_MIN_USD", "100000"))
TOKEN_RADAR_MIN_EVENT_USD = float(os.getenv("TOKEN_RADAR_MIN_EVENT_USD", "100000"))
TOKEN_SIGNAL_MIN_SCORE = int(os.getenv("TOKEN_SIGNAL_MIN_SCORE", "55"))
TOKEN_CORRELATION_WINDOW_MIN = int(os.getenv("TOKEN_CORRELATION_WINDOW_MIN", "180"))
TOKEN_DEEP_SCAN_TTL_SEC = int(os.getenv("TOKEN_DEEP_SCAN_TTL_SEC", "600"))
TOKEN_SIGNAL_COOLDOWN_MIN = int(os.getenv("TOKEN_SIGNAL_COOLDOWN_MIN", "30"))

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

PARTNER_BRIDGE_ADDRESSES = {
    x.strip().lower()
    for x in os.getenv("PARTNER_BRIDGE_ADDRESSES", "").split(",")
    if x.strip()
}

OFFICIAL_GATEWAYS = {
    L2_ERC20_GATEWAY,
    L2_CUSTOM_GATEWAY,
    L2_WETH_GATEWAY,
}

DB_PATH = os.getenv("DB_PATH", str(Path(__file__).with_name("radar.db")))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("rh-radar")


# ----------------------------
# Helpers
# ----------------------------
def norm(addr: Optional[str]) -> str:
    return (addr or "").lower()

def topic_addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()

def word(data: str, index: int) -> int:
    h = data[2:] if data.startswith("0x") else data
    start = index * 64
    return int(h[start:start+64] or "0", 16)

def data_addr(data: str, index: int) -> str:
    h = data[2:] if data.startswith("0x") else data
    start = index * 64
    return "0x" + h[start+24:start+64].lower()

def signed_word(data: str, index: int) -> int:
    v = word(data, index)
    return v - (1 << 256) if v >= (1 << 255) else v

def fmt_usd(v: Optional[float]) -> str:
    if v is None:
        return "UNKNOWN"
    return "${:,.0f}".format(v)

def fmt_amount(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:,.4f}"
    return f"{v:.8f}"

def safe_hex_int(x):
    if isinstance(x, int):
        return x
    if not x:
        return 0
    return int(x, 16)


# ----------------------------
# JSON-RPC
# ----------------------------
class RPC:
    def __init__(self, url: str):
        self.url = url
        self._local = threading.local()
        self._id = 0
        self.lock = threading.Lock()

    def _session(self):
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            self._local.session = s
        return s

    def _next_id(self):
        with self.lock:
            self._id += 1
            return self._id

    def call(self, method: str, params: list, timeout=20):
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params}
        r = self._session().post(self.url, json=payload, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            raise RuntimeError(f"RPC {method}: {j['error']}")
        return j.get("result")

    def batch(self, calls: List[Tuple[str, list]], timeout=30):
        payload = []
        ids = []
        for method, params in calls:
            rid = self._next_id()
            ids.append(rid)
            payload.append({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            r = self._session().post(self.url, json=payload, timeout=timeout)
            r.raise_for_status()
            arr = r.json()
            if not isinstance(arr, list):
                raise RuntimeError("RPC provider does not support JSON-RPC batch")
            byid = {x.get("id"): x for x in arr}
            out = []
            for rid in ids:
                item = byid.get(rid)
                if not item or "error" in item:
                    raise RuntimeError(f"RPC batch item failed: {item}")
                out.append(item.get("result"))
            return out
        except Exception as e:
            # Some public providers disable batch requests. Fall back to sequential reads
            # so the radar stays alive instead of crashing permanently.
            log.warning("RPC batch unavailable, using sequential fallback: %s", e)
            return [self.call(method, params, timeout=timeout) for method, params in calls]

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def get_logs(self, start: int, end: int):
        topics = [[
            TOPIC_V2_MINT,
            TOPIC_V2_BURN,
            TOPIC_V2_PAIR_CREATED,
            TOPIC_V3_MINT,
            TOPIC_V3_BURN,
            TOPIC_V3_POOL_CREATED,
            TOPIC_DEPOSIT_FINALIZED,
            TOPIC_V4_INITIALIZE,
            TOPIC_V4_MODIFY_LIQUIDITY,
            TOPIC_V2_SWAP,
            TOPIC_V3_SWAP,
            TOPIC_V4_SWAP,
        ]]
        return self.call("eth_getLogs", [{
            "fromBlock": hex(start),
            "toBlock": hex(end),
            "topics": topics,
        }], timeout=30) or []

    def get_blocks(self, nums: List[int], full=True):
        calls = [("eth_getBlockByNumber", [hex(n), full]) for n in nums]
        return self.batch(calls, timeout=30)

    def eth_call(self, to: str, data: str, block="latest") -> str:
        return self.call("eth_call", [{"to": to, "data": data}, block], timeout=15)


rpc = RPC(RPC_URL)


# ----------------------------
# Persistence
# ----------------------------
class ThreadLocalDB:
    """One SQLite connection per thread while preserving the old db API."""
    def __init__(self, path):
        self.path = path
        self.local = threading.local()

    def _conn(self):
        conn = getattr(self.local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=20, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            self.local.conn = conn
        return conn

    def execute(self, *args, **kwargs):
        return self._conn().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._conn().executemany(*args, **kwargs)

    def commit(self):
        return self._conn().commit()

    def rollback(self):
        return self._conn().rollback()

    def close_thread(self):
        conn = getattr(self.local, "conn", None)
        if conn is not None:
            conn.close()
            self.local.conn = None

db = ThreadLocalDB(DB_PATH)
db.execute("""
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS seen_alerts (
  k TEXT PRIMARY KEY,
  ts INTEGER NOT NULL
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS bridge_flows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  recipient TEXT NOT NULL,
  usd REAL NOT NULL,
  tx_hash TEXT NOT NULL,
  UNIQUE(tx_hash, recipient, usd)
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  severity TEXT NOT NULL,
  category TEXT NOT NULL,
  protocol TEXT NOT NULL,
  action TEXT NOT NULL,
  usd REAL,
  token_pair TEXT,
  subject TEXT,
  tx_hash TEXT,
  block_number INTEGER,
  details TEXT
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS v4_pools (
  pool_id TEXT PRIMARY KEY,
  currency0 TEXT NOT NULL,
  currency1 TEXT NOT NULL,
  fee INTEGER,
  tick_spacing INTEGER,
  hooks TEXT,
  init_sqrt_price_x96 TEXT,
  init_tick INTEGER,
  block_number INTEGER
)
""")
db.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts DESC)")
db.commit()

def kv_get(k: str) -> Optional[str]:
    row = db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return row[0] if row else None

def kv_set(k: str, v: str):
    db.execute("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (k, str(v)))
    db.commit()

def once(key: str, ttl=86400*30) -> bool:
    now = int(time.time())
    row = db.execute("SELECT ts FROM seen_alerts WHERE k=?", (key,)).fetchone()
    if row and now - row[0] < ttl:
        return False
    db.execute("INSERT OR REPLACE INTO seen_alerts(k,ts) VALUES(?,?)", (key, now))
    db.execute("DELETE FROM seen_alerts WHERE ts < ?", (now - 86400*30,))
    db.commit()
    return True

def save_alert(severity: str, category: str, protocol: str, action: str,
               usd: Optional[float], token_pair: str, subject: str,
               tx_hash: str, block_number: int, details: str):
    db.execute("""
      INSERT INTO alerts(ts,severity,category,protocol,action,usd,token_pair,subject,tx_hash,block_number,details)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """, (int(time.time()), severity, category, protocol, action, usd,
          token_pair, subject, tx_hash, block_number, details))
    db.commit()


# ----------------------------
# Telegram
# ----------------------------
def telegram(text: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        log.warning("Telegram not configured. Alert:\n%s", text)
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
            "disable_notification": False,
        }, timeout=15)
        if not r.ok:
            log.error("Telegram error %s: %s", r.status_code, r.text[:500])
    except Exception:
        log.exception("Telegram send failed")


intel = AddressIntel(
    db=db, rpc=rpc, telegram=telegram, save_alert=save_alert, explorer=EXPLORER,
    correlation_window_min=INTEL_CORRELATION_WINDOW_MIN,
    fresh_wallet_max_tx_count=FRESH_WALLET_MAX_TX_COUNT,
    bridge_min_usd=INTEL_BRIDGE_MIN_USD, lp_min_usd=INTEL_LP_MIN_USD,
    swap_min_usd=INTEL_SWAP_MIN_USD, p0_bridge_usd=ALERT_USD, p0_lp_usd=ALERT_USD,
    language=LANGUAGE,
)


# ----------------------------
# Token metadata / pricing
# ----------------------------
@dataclass
class Token:
    address: str
    symbol: str
    decimals: int

token_cache: Dict[str, Token] = {}
price_cache: Dict[str, Tuple[float, float, str]] = {}
pool_kind_cache: Dict[str, Optional[str]] = {}
pool_tokens_cache: Dict[str, Tuple[Token, Token]] = {}

token_intel = TokenIntelligence(
    rpc=rpc,
    db=db,
    explorer=EXPLORER,
    weth=WETH,
    usdg=USDG,
    v4_pool_manager=V4_POOL_MANAGER,
    language=LANGUAGE,
)

def decode_dynamic_string(raw: str) -> Optional[str]:
    try:
        h = raw[2:] if raw.startswith("0x") else raw
        if len(h) < 128:
            # bytes32-style symbol
            b = bytes.fromhex(h[:64]).rstrip(b"\x00")
            return b.decode("utf-8", errors="replace")
        offset = int(h[:64], 16)
        p = offset * 2
        ln = int(h[p:p+64], 16)
        p += 64
        return bytes.fromhex(h[p:p+ln*2]).decode("utf-8", errors="replace")
    except Exception:
        return None

def get_token(addr: str) -> Token:
    a = norm(addr)
    if a in token_cache:
        return token_cache[a]
    if a in ("", "0x0", "0x0000000000000000000000000000000000000000"):
        t = Token("0x0000000000000000000000000000000000000000", "ETH", 18)
        token_cache[t.address] = t
        return t

    symbol = a[:8]
    decimals = 18
    try:
        raw = rpc.eth_call(a, SEL_SYMBOL)
        symbol = decode_dynamic_string(raw) or symbol
    except Exception:
        pass
    try:
        raw = rpc.eth_call(a, SEL_DECIMALS)
        decimals = int(raw, 16)
        if decimals < 0 or decimals > 36:
            decimals = 18
    except Exception:
        pass

    t = Token(a, symbol[:32], decimals)
    token_cache[a] = t
    return t

# V1.3.0 token-centric capital radar. Event handlers enqueue compact records;
# a dedicated background worker performs holder/risk analysis and correlation.
token_radar = TokenRadar(
    db=db, token_intel=token_intel, token_getter=get_token, telegram=telegram,
    save_alert=save_alert, explorer=EXPLORER, weth=WETH, usdg=USDG,
    language=LANGUAGE, min_event_usd=TOKEN_RADAR_MIN_EVENT_USD,
    signal_min_score=TOKEN_SIGNAL_MIN_SCORE,
    correlation_window_min=TOKEN_CORRELATION_WINDOW_MIN,
    deep_scan_ttl_sec=TOKEN_DEEP_SCAN_TTL_SEC,
    signal_cooldown_min=TOKEN_SIGNAL_COOLDOWN_MIN,
)

def get_eth_price() -> Optional[float]:
    key = "__eth__"
    now = time.time()
    cached = price_cache.get(key)
    if cached and now - cached[0] < 30:
        return cached[1]

    urls = [
        ("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", "binance"),
        ("https://api.coinbase.com/v2/prices/ETH-USD/spot", "coinbase"),
    ]
    for url, src in urls:
        try:
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            j = r.json()
            if src == "binance":
                p = float(j["price"])
            else:
                p = float(j["data"]["amount"])
            if p > 100:
                price_cache[key] = (now, p, src)
                return p
        except Exception:
            continue
    return cached[1] if cached else None

def dexscreener_price(addr: str) -> Optional[Tuple[float, str]]:
    now = time.time()
    key = norm(addr)
    cached = price_cache.get(key)
    if cached and now - cached[0] < 60:
        return cached[1], cached[2]

    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{addr}",
            timeout=8,
        )
        if not r.ok:
            return None
        pairs = r.json().get("pairs") or []
        candidates = []
        for p in pairs:
            chain = str(p.get("chainId", "")).lower()
            if "robinhood" not in chain and chain != "4663":
                continue
            price = p.get("priceUsd")
            if not price:
                continue
            liq = ((p.get("liquidity") or {}).get("usd") or 0)
            candidates.append((float(liq), float(price)))
        if candidates:
            candidates.sort(reverse=True)
            val = candidates[0][1]
            price_cache[key] = (now, val, "dexscreener")
            return val, "dexscreener"
    except Exception:
        pass
    return None

def base_price(addr: str) -> Optional[Tuple[float, str]]:
    a = norm(addr)
    if a == USDG:
        return 1.0, "USDG"
    if a in (WETH, "", "0x0", "0x0000000000000000000000000000000000000000"):
        p = get_eth_price()
        return (p, "ETH/USD") if p else None
    return dexscreener_price(a)

def raw_to_human(raw: int, decimals: int) -> float:
    return raw / (10 ** decimals)

def get_pool_tokens(pool: str) -> Tuple[Token, Token]:
    p = norm(pool)
    if p in pool_tokens_cache:
        return pool_tokens_cache[p]
    r0, r1 = rpc.batch([
        ("eth_call", [{"to": p, "data": SEL_TOKEN0}, "latest"]),
        ("eth_call", [{"to": p, "data": SEL_TOKEN1}, "latest"]),
    ])
    a0 = "0x" + r0[-40:].lower()
    a1 = "0x" + r1[-40:].lower()
    pair = (get_token(a0), get_token(a1))
    pool_tokens_cache[p] = pair
    return pair

def get_pool_kind(pool: str) -> Optional[str]:
    p = norm(pool)
    if p in pool_kind_cache:
        return pool_kind_cache[p]
    kind = None
    try:
        raw = rpc.eth_call(p, SEL_FACTORY)
        f = "0x" + raw[-40:].lower()
        if f == V2_FACTORY:
            kind = "v2"
        elif f == V3_FACTORY:
            kind = "v3"
    except Exception:
        pass
    pool_kind_cache[p] = kind
    return kind

def derive_pair_prices_v3(pool: str, t0: Token, t1: Token):
    p0 = base_price(t0.address)
    p1 = base_price(t1.address)
    if p0 and p1:
        return p0[0], p1[0], f"{p0[1]}+{p1[1]}"

    try:
        raw = rpc.eth_call(pool, SEL_SLOT0)
        sqrt_price_x96 = word(raw, 0)
        if sqrt_price_x96 <= 0:
            return (p0[0] if p0 else None, p1[0] if p1 else None, "unknown")
        ratio = (sqrt_price_x96 / (2 ** 96)) ** 2 * (10 ** (t0.decimals - t1.decimals))
        if ratio <= 0 or not math.isfinite(ratio):
            raise ValueError("bad ratio")
        if p0 and not p1:
            return p0[0], p0[0] / ratio, f"{p0[1]}+pool-spot"
        if p1 and not p0:
            return ratio * p1[0], p1[0], f"{p1[1]}+pool-spot"
    except Exception:
        pass
    return (p0[0] if p0 else None, p1[0] if p1 else None, "partial")

def derive_pair_prices_v2(pool: str, t0: Token, t1: Token):
    p0 = base_price(t0.address)
    p1 = base_price(t1.address)
    if p0 and p1:
        return p0[0], p1[0], f"{p0[1]}+{p1[1]}"

    try:
        raw = rpc.eth_call(pool, SEL_GET_RESERVES)
        r0 = word(raw, 0)
        r1 = word(raw, 1)
        if r0 <= 0 or r1 <= 0:
            raise ValueError("zero reserve")
        h0 = raw_to_human(r0, t0.decimals)
        h1 = raw_to_human(r1, t1.decimals)
        ratio = h1 / h0  # token1 per token0
        if p0 and not p1:
            return p0[0], p0[0] / ratio, f"{p0[1]}+pool-spot"
        if p1 and not p0:
            return ratio * p1[0], p1[0], f"{p1[1]}+pool-spot"
    except Exception:
        pass
    return (p0[0] if p0 else None, p1[0] if p1 else None, "partial")

def value_pair(pool: str, kind: str, raw0: int, raw1: int):
    t0, t1 = get_pool_tokens(pool)
    a0 = raw_to_human(raw0, t0.decimals)
    a1 = raw_to_human(raw1, t1.decimals)
    if kind == "v3":
        p0, p1, src = derive_pair_prices_v3(pool, t0, t1)
    else:
        p0, p1, src = derive_pair_prices_v2(pool, t0, t1)

    usd = 0.0
    known = False
    if p0 is not None:
        usd += a0 * p0
        known = True
    if p1 is not None:
        usd += a1 * p1
        known = True
    return (usd if known else None), t0, t1, a0, a1, src

def calc_l2_token(l1_token: str) -> Optional[str]:
    try:
        arg = l1_token[2:].rjust(64, "0")
        raw = rpc.eth_call(L2_GATEWAY_ROUTER, SEL_CALC_L2 + arg)
        a = "0x" + raw[-40:].lower()
        if int(a, 16) == 0:
            return None
        return a
    except Exception:
        return None


# ----------------------------
# Uniswap V4
# ----------------------------
def v4_store_pool(pool_id: str, currency0: str, currency1: str, fee: int,
                  tick_spacing: int, hooks: str, sqrt_price_x96: int,
                  init_tick: int, block_number: int):
    db.execute("""
      INSERT OR REPLACE INTO v4_pools(
        pool_id,currency0,currency1,fee,tick_spacing,hooks,
        init_sqrt_price_x96,init_tick,block_number
      ) VALUES(?,?,?,?,?,?,?,?,?)
    """, (pool_id.lower(), norm(currency0), norm(currency1), int(fee), int(tick_spacing),
          norm(hooks), str(int(sqrt_price_x96)), int(init_tick), int(block_number)))
    db.commit()

def v4_get_pool(pool_id: str):
    row = db.execute("""
      SELECT pool_id,currency0,currency1,fee,tick_spacing,hooks,
             init_sqrt_price_x96,init_tick,block_number
      FROM v4_pools WHERE pool_id=?
    """, (pool_id.lower(),)).fetchone()
    if not row:
        return None
    keys=("pool_id","currency0","currency1","fee","tick_spacing","hooks",
          "init_sqrt_price_x96","init_tick","block_number")
    return dict(zip(keys,row))

def _v4_decode_initialize(lg):
    topics=lg.get("topics") or []
    if len(topics)<4:
        return None
    return {
      "pool_id":topics[1].lower(),
      "currency0":topic_addr(topics[2]),
      "currency1":topic_addr(topics[3]),
      "fee":word(lg["data"],0),
      "tick_spacing":signed_word(lg["data"],1),
      "hooks":data_addr(lg["data"],2),
      "sqrt_price_x96":word(lg["data"],3),
      "init_tick":signed_word(lg["data"],4),
      "block_number":safe_hex_int(lg["blockNumber"]),
    }

def process_v4_initialize(lg):
    if norm(lg["address"])!=V4_POOL_MANAGER:
        return
    info=_v4_decode_initialize(lg)
    if not info:
        return
    v4_store_pool(**info)
    intel.register_pool(
        info["pool_id"], "v4", info["currency0"], info["currency1"],
        info["block_number"], lg.get("transactionHash")
    )
    # Keep Initialize processing deliberately lightweight. Token metadata is
    # resolved only when a pool actually has a material LP/swap event.
    log.info("New Uniswap V4 pool: %s %s/%s", info["pool_id"],
             info["currency0"][:10], info["currency1"][:10])

def v4_find_pool_init(pool_id: str, current_block: int):
    cached=v4_get_pool(pool_id)
    if cached:
        return cached
    end=int(current_block)
    window=1_000_000
    while end>=0:
        start=max(0,end-window+1)
        try:
            logs=rpc.call("eth_getLogs", [{
              "fromBlock":hex(start),"toBlock":hex(end),"address":V4_POOL_MANAGER,
              "topics":[TOPIC_V4_INITIALIZE,pool_id],
            }], timeout=25) or []
            if logs:
                info=_v4_decode_initialize(logs[-1])
                if info:
                    v4_store_pool(**info)
                    return v4_get_pool(pool_id)
            end=start-1
        except Exception:
            if window>50_000:
                window//=2
            else:
                end=start-1
    return None

def v4_get_slot0(pool_id: str, block_number: Optional[int]=None):
    pid=pool_id[2:] if pool_id.startswith("0x") else pool_id
    raw=rpc.eth_call(V4_STATE_VIEW, SEL_V4_GET_SLOT0+pid.rjust(64,"0"),
                     hex(block_number) if block_number is not None else "latest")
    return word(raw,0), signed_word(raw,1), word(raw,2), word(raw,3)

def sqrt_price_x96_at_tick(tick: int) -> int:
    return max(1,int((1.0001 ** (tick/2.0))*(2**96)))

def v4_principal_amounts(liquidity_abs: int, sqrt_p: int, tick_lower: int, tick_upper: int):
    if liquidity_abs<=0:
        return 0,0
    q96=2**96
    sa=sqrt_price_x96_at_tick(tick_lower); sb=sqrt_price_x96_at_tick(tick_upper)
    if sa>sb: sa,sb=sb,sa
    if sqrt_p<=sa:
        return int(liquidity_abs*(sb-sa)*q96//(sb*sa)),0
    if sqrt_p<sb:
        a0=liquidity_abs*(sb-sqrt_p)*q96//(sb*sqrt_p)
        a1=liquidity_abs*(sqrt_p-sa)//q96
        return int(a0),int(a1)
    return 0,int(liquidity_abs*(sb-sa)//q96)

def process_v4_modify_liquidity(lg):
    if norm(lg["address"])!=V4_POOL_MANAGER:
        return
    topics=lg.get("topics") or []
    if len(topics)<3:
        return
    pool_id=topics[1].lower(); sender=topic_addr(topics[2])
    tick_lower=signed_word(lg["data"],0); tick_upper=signed_word(lg["data"],1)
    liquidity_delta=signed_word(lg["data"],2)
    if liquidity_delta==0:
        return
    block_num=safe_hex_int(lg["blockNumber"])
    pool=v4_get_pool(pool_id) or v4_find_pool_init(pool_id,block_num)
    if not pool:
        log.warning("V4 pool metadata unresolved: %s",pool_id); return
    try:
        sqrt_p,current_tick,_,_=v4_get_slot0(pool_id,block_num)
    except Exception:
        sqrt_p,current_tick,_,_=v4_get_slot0(pool_id,None)
    raw0,raw1=v4_principal_amounts(abs(liquidity_delta),sqrt_p,tick_lower,tick_upper)
    t0=get_token(pool["currency0"]); t1=get_token(pool["currency1"])
    a0=raw_to_human(raw0,t0.decimals); a1=raw_to_human(raw1,t1.decimals)
    p0=base_price(t0.address); p1=base_price(t1.address)
    price0=p0[0] if p0 else None; price1=p1[0] if p1 else None
    sources=[]
    if p0:sources.append(p0[1])
    if p1:sources.append(p1[1])
    try:
        ratio=(sqrt_p/(2**96))**2*(10**(t0.decimals-t1.decimals))
        if not math.isfinite(ratio) or ratio<=0: ratio=None
    except Exception:
        ratio=None
    if ratio:
        if price0 is not None and price1 is None:
            price1=price0/ratio; sources.append("v4-pool-spot")
        elif price1 is not None and price0 is None:
            price0=ratio*price1; sources.append("v4-pool-spot")
    usd=0.0; known=False
    if price0 is not None: usd+=a0*price0; known=True
    if price1 is not None: usd+=a1*price1; known=True
    if not known:
        return
    action="ADD" if liquidity_delta>0 else "REMOVE"
    new_pool = action=="ADD" and block_num-int(pool.get("block_number") or 0)<=1000
    if new_pool:
        action="NEW POOL ADD"
    pair=f"{t0.symbol}/{t1.symbol}"
    actor=intel.actor_for_tx(lg["transactionHash"],sender)
    intel.record(actor,"liquidity","Uniswap V4",action,usd,pair,pool_id,
                 lg["transactionHash"],block_num,
                 {"new_pool":bool(new_pool),"event_sender":sender,
                  "tick_lower":tick_lower,"tick_upper":tick_upper,"current_tick":current_tick,
                  "token0":t0.address,"token1":t1.address})
    token_radar.observe_liquidity(
        "v4", action, pool_id, usd, t0, t1, actor, lg["transactionHash"], block_num,
        new_pool=bool(new_pool), metadata={"tick_lower":tick_lower,"tick_upper":tick_upper,
                                          "current_tick":current_tick,"hooks":pool.get("hooks")}
    )
    if usd<ALERT_USD:
        return
    key=f"v4liq:{lg['transactionHash']}:{pool_id}:{action}:{tick_lower}:{tick_upper}"
    if not once(key): return
    hooks=pool.get("hooks") or "0x0"
    zero="0x0000000000000000000000000000000000000000"
    confidence="HIGH" if hooks==zero else "MEDIUM"
    source="+".join(dict.fromkeys(sources)) if sources else "v4-pool-spot"
    action_zh={"ADD":"加池","REMOVE":"撤池","NEW POOL ADD":"新池加池"}.get(action,action)
    action_en={"ADD":"Add Liquidity","REMOVE":"Remove Liquidity","NEW POOL ADD":"New Pool + Add Liquidity"}.get(action,action)
    confidence_zh={"HIGH":"高","MEDIUM":"中","LOW":"低"}.get(confidence,confidence)
    if LANGUAGE.lower().startswith("zh"):
        text=(
          "🚨 Robinhood 链 · 百万美元级 V4 流动性\n"
          f"类型：Uniswap V4 · {action_zh}\n"
          f"本金估算：{fmt_usd(usd)}\n"
          f"交易对：{pair}\n{t0.symbol}：{fmt_amount(a0)}\n{t1.symbol}：{fmt_amount(a1)}\n"
          f"Tick 区间：[{tick_lower}, {tick_upper}] · 当前 Tick {current_tick}\n"
          f"置信度：{confidence_zh}\n定价来源：{source}\nPool ID：{pool_id}\n事件发送方：{sender}\n"
          f"区块：{block_num}\n交易：{EXPLORER}/tx/{lg['transactionHash']}\n"
          "说明：金额为 V4 LP 本金估算，不包含手续费和 Hook 的额外资产变化。"
        )
    else:
        text=(
          "🚨 Robinhood Chain · $1M+ V4 Liquidity\n"
          f"Type: Uniswap V4 · {action_en}\n"
          f"Principal estimate: {fmt_usd(usd)}\n"
          f"Pair: {pair}\n{t0.symbol}: {fmt_amount(a0)}\n{t1.symbol}: {fmt_amount(a1)}\n"
          f"Tick range: [{tick_lower}, {tick_upper}] · current {current_tick}\n"
          f"Confidence: {confidence}\nPricing: {source}\nPool ID: {pool_id}\nEvent sender: {sender}\n"
          f"Block: {block_num}\nTx: {EXPLORER}/tx/{lg['transactionHash']}\n"
          "Note: amount is an estimated V4 LP principal and excludes fees and Hook deltas."
        )
    try:
        extra = token_intel.build_liquidity_report(
            kind="v4",
            pool_subject=pool_id,
            event_usd=usd,
            t0=t0,
            t1=t1,
            block_number=block_num,
            v4_meta=pool,
            current_amounts=(a0, a1),
        )
        if extra:
            text += "\n\n" + extra
    except Exception as e:
        log.warning("Token intelligence enrichment failed: %s", e)

    save_alert("P1","liquidity","Uniswap V4",action,usd,pair,pool_id,
               lg["transactionHash"],block_num,
               f"range={tick_lower}:{tick_upper}; current={current_tick}; confidence={confidence}; pricing={source}")
    log.warning(text.replace("\n"," | ")); telegram(text)

# ----------------------------
# Alert builders
# ----------------------------
def liquidity_alert(kind: str, action: str, pool: str, txh: str, usd: float,
                    t0: Token, t1: Token, a0: float, a1: float, src: str,
                    block: int):
    key = f"liq:{txh}:{pool}:{action}"
    if not once(key):
        return
    action_zh={"ADD":"加池","REMOVE":"撤池","NEW POOL ADD":"新池加池"}.get(action,action)
    action_en={"ADD":"Add Liquidity","REMOVE":"Remove Liquidity","NEW POOL ADD":"New Pool + Add Liquidity"}.get(action,action)
    if LANGUAGE.lower().startswith("zh"):
        text = (
            "🚨 Robinhood 链 · 百万美元级流动性\n"
            f"类型：Uniswap {kind.upper()} · {action_zh}\n"
            f"估值：{fmt_usd(usd)}\n"
            f"交易对：{t0.symbol} / {t1.symbol}\n"
            f"{t0.symbol}：{fmt_amount(a0)}\n"
            f"{t1.symbol}：{fmt_amount(a1)}\n"
            f"定价来源：{src}\n"
            f"池地址：{pool}\n"
            f"区块：{block}\n"
            f"交易：{EXPLORER}/tx/{txh}"
        )
    else:
        text = (
            "🚨 Robinhood Chain · $1M+ Liquidity\n"
            f"Type: Uniswap {kind.upper()} · {action_en}\n"
            f"Value: {fmt_usd(usd)}\n"
            f"Pair: {t0.symbol} / {t1.symbol}\n"
            f"{t0.symbol}: {fmt_amount(a0)}\n"
            f"{t1.symbol}: {fmt_amount(a1)}\n"
            f"Pricing: {src}\n"
            f"Pool: {pool}\n"
            f"Block: {block}\n"
            f"Tx: {EXPLORER}/tx/{txh}"
        )
    try:
        extra = token_intel.build_liquidity_report(
            kind=kind,
            pool_subject=pool,
            event_usd=usd,
            t0=t0,
            t1=t1,
            block_number=block,
            current_amounts=(a0, a1),
        )
        if extra:
            text += "\n\n" + extra
    except Exception as e:
        log.warning("Token intelligence enrichment failed: %s", e)

    save_alert("P1","liquidity",f"Uniswap {kind.upper()}",action,usd,
               f"{t0.symbol}/{t1.symbol}",pool,txh,block,
               f"{t0.symbol}={a0}; {t1.symbol}={a1}; pricing={src}")
    log.warning(text.replace("\n", " | "))
    telegram(text)

def bridge_alert(bridge: str, txh: str, recipient: str, token: Token,
                 amount: float, usd: float, block: int):
    key = f"bridge:{txh}:{recipient}:{token.address}:{amount}"
    if not once(key):
        return
    text = (
        "🚨 Robinhood 链 · 百万美元级跨链流入\n"
        f"跨链通道：{bridge}\n"
        f"估值：{fmt_usd(usd)}\n"
        f"代币：{token.symbol}\n"
        f"数量：{fmt_amount(amount)}\n"
        f"接收地址：{recipient}\n"
        f"区块：{block}\n"
        f"交易：{EXPLORER}/tx/{txh}"
    ) if LANGUAGE.lower().startswith("zh") else (
        "🚨 Robinhood Chain · $1M+ Bridge In\n"
        f"Bridge: {bridge}\n"
        f"Value: {fmt_usd(usd)}\n"
        f"Token: {token.symbol}\n"
        f"Amount: {fmt_amount(amount)}\n"
        f"Recipient: {recipient}\n"
        f"Block: {block}\n"
        f"Tx: {EXPLORER}/tx/{txh}"
    )
    save_alert("P1","bridge",bridge,"BRIDGE IN",usd,token.symbol,recipient,txh,block,
               f"amount={amount}; token={token.address}")
    log.warning(text.replace("\n", " | "))
    telegram(text)

def native_bridge_alert(txh: str, recipient: str, eth_amount: float,
                        usd: float, block: int):
    key = f"native:{txh}"
    if not once(key):
        return
    text = (
        "🚨 Robinhood 链 · 百万美元级 ETH 跨链流入\n"
        "跨链通道：官方 Canonical ETH（Arbitrum Deposit 0x64）\n"
        f"估值：{fmt_usd(usd)}\n"
        "代币：ETH\n"
        f"数量：{fmt_amount(eth_amount)}\n"
        f"接收地址：{recipient}\n"
        f"区块：{block}\n"
        f"交易：{EXPLORER}/tx/{txh}"
    ) if LANGUAGE.lower().startswith("zh") else (
        "🚨 Robinhood Chain · $1M+ ETH Bridge In\n"
        "Bridge: Canonical ETH (Arbitrum Deposit 0x64)\n"
        f"Value: {fmt_usd(usd)}\n"
        "Token: ETH\n"
        f"Amount: {fmt_amount(eth_amount)}\n"
        f"Recipient: {recipient}\n"
        f"Block: {block}\n"
        f"Tx: {EXPLORER}/tx/{txh}"
    )
    save_alert("P1","bridge","Canonical ETH","BRIDGE IN",usd,"ETH",recipient,txh,block,
               f"amount={eth_amount}")
    log.warning(text.replace("\n", " | "))
    telegram(text)

def record_bridge_flow(recipient: str, usd: float, txh: str):
    now = int(time.time())
    try:
        db.execute(
            "INSERT OR IGNORE INTO bridge_flows(ts,recipient,usd,tx_hash) VALUES(?,?,?,?)",
            (now, recipient.lower(), usd, txh),
        )
        db.execute("DELETE FROM bridge_flows WHERE ts < ?", (now - CUM_WINDOW_SECONDS * 2,))
        db.commit()
        total = db.execute(
            "SELECT COALESCE(SUM(usd),0) FROM bridge_flows WHERE recipient=? AND ts>=?",
            (recipient.lower(), now - CUM_WINDOW_SECONDS),
        ).fetchone()[0]
        if total >= CUM_ALERT_USD:
            bucket = now // max(CUM_WINDOW_SECONDS, 60)
            key = f"cum:{recipient.lower()}:{bucket}"
            if once(key, ttl=CUM_WINDOW_SECONDS):
                save_alert("P2","bridge","Aggregate","CUMULATIVE",total,"",recipient,txh,0,
                           f"window={CUM_WINDOW_SECONDS//60}min")
                telegram(
                    (
                        "🔥 Robinhood 链 · 累计大额跨链\n"
                        f"统计窗口：{CUM_WINDOW_SECONDS//60} 分钟\n"
                        f"地址：{recipient}\n"
                        f"累计流入：{fmt_usd(total)}"
                    ) if LANGUAGE.lower().startswith("zh") else (
                        "🔥 Robinhood Chain · Cumulative Bridge In\n"
                        f"Window: {CUM_WINDOW_SECONDS//60} min\n"
                        f"Address: {recipient}\n"
                        f"Total inflow: {fmt_usd(total)}"
                    )
                )
    except Exception:
        log.exception("bridge aggregation failed")


# ----------------------------
# Event processing
# ----------------------------
def process_v2_mint(lg):
    pool=norm(lg["address"])
    if get_pool_kind(pool)!="v2": return
    raw0,raw1=word(lg["data"],0),word(lg["data"],1)
    usd,t0,t1,a0,a1,src=value_pair(pool,"v2",raw0,raw1)
    if usd is None: return
    block=safe_hex_int(lg["blockNumber"]); txh=lg["transactionHash"]
    event_sender=topic_addr(lg["topics"][1]) if len(lg.get("topics",[]))>1 else ""
    actor=intel.actor_for_tx(txh,event_sender); pair=f"{t0.symbol}/{t1.symbol}"
    new_pool=intel.pool_is_new(pool,block)
    action="NEW POOL ADD" if new_pool else "ADD"
    intel.record(actor,"liquidity","Uniswap V2",action,usd,pair,pool,txh,block,{"new_pool":new_pool,"event_sender":event_sender,"pricing":src,"token0":t0.address,"token1":t1.address})
    token_radar.observe_liquidity("v2",action,pool,usd,t0,t1,actor,txh,block,new_pool=new_pool,metadata={"pricing":src})
    if usd>=ALERT_USD: liquidity_alert("v2",action,pool,txh,usd,t0,t1,a0,a1,src,block)
def process_v2_burn(lg):
    pool=norm(lg["address"])
    if get_pool_kind(pool)!="v2": return
    raw0,raw1=word(lg["data"],0),word(lg["data"],1)
    usd,t0,t1,a0,a1,src=value_pair(pool,"v2",raw0,raw1)
    if usd is None: return
    block=safe_hex_int(lg["blockNumber"]); txh=lg["transactionHash"]
    event_sender=topic_addr(lg["topics"][1]) if len(lg.get("topics",[]))>1 else ""
    actor=intel.actor_for_tx(txh,event_sender)
    intel.record(actor,"liquidity","Uniswap V2","REMOVE",usd,f"{t0.symbol}/{t1.symbol}",pool,txh,block,{"event_sender":event_sender,"pricing":src,"token0":t0.address,"token1":t1.address})
    token_radar.observe_liquidity("v2","REMOVE",pool,usd,t0,t1,actor,txh,block,metadata={"pricing":src})
    if usd>=ALERT_USD: liquidity_alert("v2","REMOVE",pool,txh,usd,t0,t1,a0,a1,src,block)
def process_v3_mint(lg):
    pool=norm(lg["address"])
    if get_pool_kind(pool)!="v3": return
    raw0,raw1=word(lg["data"],2),word(lg["data"],3)
    usd,t0,t1,a0,a1,src=value_pair(pool,"v3",raw0,raw1)
    if usd is None: return
    block=safe_hex_int(lg["blockNumber"]); txh=lg["transactionHash"]
    event_sender=data_addr(lg["data"],0); actor=intel.actor_for_tx(txh,event_sender)
    pair=f"{t0.symbol}/{t1.symbol}"; new_pool=intel.pool_is_new(pool,block)
    action="NEW POOL ADD" if new_pool else "ADD"
    intel.record(actor,"liquidity","Uniswap V3",action,usd,pair,pool,txh,block,{"new_pool":new_pool,"event_sender":event_sender,"pricing":src,"token0":t0.address,"token1":t1.address})
    token_radar.observe_liquidity("v3",action,pool,usd,t0,t1,actor,txh,block,new_pool=new_pool,metadata={"pricing":src})
    if usd>=ALERT_USD: liquidity_alert("v3",action,pool,txh,usd,t0,t1,a0,a1,src,block)
def process_v3_burn(lg):
    pool=norm(lg["address"])
    if get_pool_kind(pool)!="v3": return
    raw0,raw1=word(lg["data"],1),word(lg["data"],2)
    usd,t0,t1,a0,a1,src=value_pair(pool,"v3",raw0,raw1)
    if usd is None: return
    block=safe_hex_int(lg["blockNumber"]); txh=lg["transactionHash"]
    event_sender=topic_addr(lg["topics"][1]) if len(lg.get("topics",[]))>1 else ""
    actor=intel.actor_for_tx(txh,event_sender)
    intel.record(actor,"liquidity","Uniswap V3","REMOVE",usd,f"{t0.symbol}/{t1.symbol}",pool,txh,block,{"event_sender":event_sender,"pricing":src,"token0":t0.address,"token1":t1.address})
    token_radar.observe_liquidity("v3","REMOVE",pool,usd,t0,t1,actor,txh,block,metadata={"pricing":src})
    if usd>=ALERT_USD: liquidity_alert("v3","REMOVE",pool,txh,usd,t0,t1,a0,a1,src,block)
def process_pool_created(lg, version: str):
    addr = norm(lg["address"])
    expected = V2_FACTORY if version == "v2" else V3_FACTORY
    if addr != expected:
        return
    if version == "v2":
        pair = data_addr(lg["data"], 0)
        token0 = topic_addr(lg["topics"][1])
        token1 = topic_addr(lg["topics"][2])
        pool_kind_cache[pair] = "v2"
        intel.register_pool(pair,"v2",token0,token1,safe_hex_int(lg["blockNumber"]),lg.get("transactionHash"))
        log.info("New Uniswap V2 pair: %s %s/%s", pair, token0, token1)
    else:
        pool = data_addr(lg["data"], 1)
        token0 = topic_addr(lg["topics"][1])
        token1 = topic_addr(lg["topics"][2])
        pool_kind_cache[pool] = "v3"
        intel.register_pool(pool,"v3",token0,token1,safe_hex_int(lg["blockNumber"]),lg.get("transactionHash"))
        log.info("New Uniswap V3 pool: %s %s/%s", pool, token0, token1)

def process_deposit_finalized(lg):
    gateway = norm(lg["address"])
    if gateway not in OFFICIAL_GATEWAYS and gateway not in PARTNER_BRIDGE_ADDRESSES:
        return
    if len(lg.get("topics", [])) < 4:
        return

    l1_token = topic_addr(lg["topics"][1])
    recipient = topic_addr(lg["topics"][3])
    raw_amt = word(lg["data"], 0)

    if gateway == L2_WETH_GATEWAY:
        l2_token = WETH
        bridge_name = "Canonical WETH Gateway"
    else:
        l2_token = calc_l2_token(l1_token)
        bridge_name = (
            "Canonical ERC20 Gateway"
            if gateway in OFFICIAL_GATEWAYS
            else "Configured Partner Bridge"
        )

    if not l2_token:
        log.info("Bridge deposit token mapping unknown: L1=%s tx=%s", l1_token, lg["transactionHash"])
        return

    token = get_token(l2_token)
    amount = raw_to_human(raw_amt, token.decimals)
    p = base_price(token.address)
    if not p:
        log.info("Bridge deposit unpriced: %s %s tx=%s", amount, token.symbol, lg["transactionHash"])
        return
    usd = amount * p[0]
    block_num=safe_hex_int(lg["blockNumber"])
    intel.record(recipient,"bridge",bridge_name,"BRIDGE IN",usd,token.symbol,recipient,lg["transactionHash"],block_num,{"token":token.address,"amount":amount})
    token_radar.observe_bridge(token.address,token.symbol,usd,recipient,bridge_name,lg["transactionHash"],block_num,{"amount":amount})
    record_bridge_flow(recipient, usd, lg["transactionHash"])
    if usd >= ALERT_USD:
        bridge_alert(
            bridge_name,
            lg["transactionHash"],
            recipient,
            token,
            amount,
            usd,
            block_num,
        )


def _swap_input_usd(t0,t1,raw0,raw1,pool,kind):
    a0=raw_to_human(abs(int(raw0)),t0.decimals); a1=raw_to_human(abs(int(raw1)),t1.decimals)
    if kind=="v3": p0,p1,src=derive_pair_prices_v3(pool,t0,t1)
    else: p0,p1,src=derive_pair_prices_v2(pool,t0,t1)
    usd=None
    if raw0>0 and p0 is not None: usd=a0*p0
    elif raw1>0 and p1 is not None: usd=a1*p1
    else:
        vals=[]
        if p0 is not None: vals.append(a0*p0)
        if p1 is not None: vals.append(a1*p1)
        if vals: usd=max(vals)
    return usd,a0,a1,src

def process_v2_swap(lg):
    pool=norm(lg["address"])
    if get_pool_kind(pool)!="v2": return
    a0in,a1in,a0out,a1out=word(lg["data"],0),word(lg["data"],1),word(lg["data"],2),word(lg["data"],3)
    t0,t1=get_pool_tokens(pool); raw0=a0in if a0in else -a0out; raw1=a1in if a1in else -a1out
    usd,_,_,src=_swap_input_usd(t0,t1,raw0,raw1,pool,"v2")
    if usd is None or usd<INTEL_SWAP_MIN_USD: return
    txh=lg["transactionHash"]; block=safe_hex_int(lg["blockNumber"]); event_sender=topic_addr(lg["topics"][1]) if len(lg.get("topics",[]))>1 else ""
    actor=intel.actor_for_tx(txh,event_sender)
    focus,_,idx=token_radar.focus_token(t0,t1); direction="BUY" if (raw0 if idx==0 else raw1)<0 else "SELL"
    intel.record(actor,"swap","Uniswap V2",direction,usd,f"{t0.symbol}/{t1.symbol}",pool,txh,block,{"event_sender":event_sender,"pricing":src,"token0":t0.address,"token1":t1.address,"focus_token":focus.address})
    token_radar.observe_swap("v2",pool,usd,t0,t1,raw0,raw1,actor,txh,block,{"pricing":src})

def process_v3_swap(lg):
    pool=norm(lg["address"])
    if get_pool_kind(pool)!="v3": return
    raw0,raw1=signed_word(lg["data"],0),signed_word(lg["data"],1); t0,t1=get_pool_tokens(pool)
    usd,_,_,src=_swap_input_usd(t0,t1,raw0,raw1,pool,"v3")
    if usd is None or usd<INTEL_SWAP_MIN_USD: return
    txh=lg["transactionHash"]; block=safe_hex_int(lg["blockNumber"]); event_sender=topic_addr(lg["topics"][1]) if len(lg.get("topics",[]))>1 else ""
    actor=intel.actor_for_tx(txh,event_sender)
    focus,_,idx=token_radar.focus_token(t0,t1); direction="BUY" if (raw0 if idx==0 else raw1)<0 else "SELL"
    intel.record(actor,"swap","Uniswap V3",direction,usd,f"{t0.symbol}/{t1.symbol}",pool,txh,block,{"event_sender":event_sender,"pricing":src,"token0":t0.address,"token1":t1.address,"focus_token":focus.address})
    token_radar.observe_swap("v3",pool,usd,t0,t1,raw0,raw1,actor,txh,block,{"pricing":src})

def process_v4_swap(lg):
    if norm(lg["address"])!=V4_POOL_MANAGER: return
    topics=lg.get("topics") or []
    if len(topics)<3: return
    pool_id=topics[1].lower(); event_sender=topic_addr(topics[2]); block=safe_hex_int(lg["blockNumber"])
    pool=v4_get_pool(pool_id) or v4_find_pool_init(pool_id,block)
    if not pool: return
    raw0,raw1=signed_word(lg["data"],0),signed_word(lg["data"],1); t0,t1=get_token(pool["currency0"]),get_token(pool["currency1"])
    p0,p1=base_price(t0.address),base_price(t1.address); sqrt_p=word(lg["data"],2); ratio=None
    try:
        ratio=(sqrt_p/(2**96))**2*(10**(t0.decimals-t1.decimals))
        if not math.isfinite(ratio) or ratio<=0: ratio=None
    except Exception: ratio=None
    price0=p0[0] if p0 else None; price1=p1[0] if p1 else None; sources=[]
    if p0: sources.append(p0[1])
    if p1: sources.append(p1[1])
    if ratio:
        if price0 is not None and price1 is None: price1=price0/ratio; sources.append("v4-pool-spot")
        elif price1 is not None and price0 is None: price0=ratio*price1; sources.append("v4-pool-spot")
    a0=raw_to_human(abs(raw0),t0.decimals); a1=raw_to_human(abs(raw1),t1.decimals); usd=None
    if raw0>0 and price0 is not None: usd=a0*price0
    elif raw1>0 and price1 is not None: usd=a1*price1
    else:
        vals=[]
        if price0 is not None: vals.append(a0*price0)
        if price1 is not None: vals.append(a1*price1)
        if vals: usd=max(vals)
    if usd is None or usd<INTEL_SWAP_MIN_USD: return
    txh=lg["transactionHash"]; actor=intel.actor_for_tx(txh,event_sender)
    focus,_,idx=token_radar.focus_token(t0,t1); direction="BUY" if (raw0 if idx==0 else raw1)<0 else "SELL"
    pricing="+".join(dict.fromkeys(sources))
    intel.record(actor,"swap","Uniswap V4",direction,usd,f"{t0.symbol}/{t1.symbol}",pool_id,txh,block,{"event_sender":event_sender,"pricing":pricing,"tick":signed_word(lg["data"],4),"fee":word(lg["data"],5),"token0":t0.address,"token1":t1.address,"focus_token":focus.address})
    token_radar.observe_swap("v4",pool_id,usd,t0,t1,raw0,raw1,actor,txh,block,{"pricing":pricing,"tick":signed_word(lg["data"],4),"fee":word(lg["data"],5)})

def process_log(lg):
    try:
        t0 = (lg.get("topics") or [""])[0].lower()
        if t0 == TOPIC_V2_MINT.lower():
            process_v2_mint(lg)
        elif t0 == TOPIC_V2_BURN.lower():
            process_v2_burn(lg)
        elif t0 == TOPIC_V2_PAIR_CREATED.lower():
            process_pool_created(lg, "v2")
        elif t0 == TOPIC_V3_MINT.lower():
            process_v3_mint(lg)
        elif t0 == TOPIC_V3_BURN.lower():
            process_v3_burn(lg)
        elif t0 == TOPIC_V3_POOL_CREATED.lower():
            process_pool_created(lg, "v3")
        elif t0 == TOPIC_DEPOSIT_FINALIZED.lower():
            process_deposit_finalized(lg)
        elif t0 == TOPIC_V4_INITIALIZE.lower():
            process_v4_initialize(lg)
        elif t0 == TOPIC_V4_MODIFY_LIQUIDITY.lower():
            process_v4_modify_liquidity(lg)
        elif t0 == TOPIC_V2_SWAP.lower():
            process_v2_swap(lg)
        elif t0 == TOPIC_V3_SWAP.lower():
            process_v3_swap(lg)
        elif t0 == TOPIC_V4_SWAP.lower():
            process_v4_swap(lg)
    except Exception:
        log.exception("Failed processing log tx=%s", lg.get("transactionHash"))
        raise


# ----------------------------
# Native ETH deposits
# ----------------------------
def process_native_deposits(blocks):
    eth_price = None
    for b in blocks:
        if not b:
            continue
        bn = safe_hex_int(b.get("number"))
        for tx in b.get("transactions") or []:
            try:
                typ = str(tx.get("type", "")).lower()
                if typ not in ("0x64", "0x064"):
                    continue
                value_wei = safe_hex_int(tx.get("value"))
                if value_wei <= 0:
                    continue
                amount = value_wei / 1e18
                if eth_price is None:
                    eth_price = get_eth_price()
                if not eth_price:
                    continue
                usd = amount * eth_price
                recipient = tx.get("to") or tx.get("from") or "unknown"
                intel.record(recipient,"bridge","Canonical ETH","BRIDGE IN",usd,"ETH",recipient,tx.get("hash"),bn,{"amount":amount})
                record_bridge_flow(recipient, usd, tx.get("hash"))
                if usd >= ALERT_USD:
                    native_bridge_alert(
                        tx.get("hash"),
                        recipient,
                        amount,
                        usd,
                        bn,
                    )
            except Exception:
                log.exception("Native deposit processing failed")


# ----------------------------
# Main loop
# ----------------------------
def healthcheck():
    cid = int(rpc.call("eth_chainId", []), 16)
    if cid != CHAIN_ID:
        raise RuntimeError(f"Wrong network: chainId={cid}, expected {CHAIN_ID}")
    latest = rpc.block_number()
    log.info("Connected Robinhood Chain | chain=%s | latest=%s", cid, latest)
    return latest

def send_startup(latest):
    telegram(
        (
            "✅ Robinhood 链资金雷达已启动\n"
            f"链 ID：{CHAIN_ID}\n"
            f"警报门槛：{fmt_usd(ALERT_USD)}\n"
            f"RPC：{RPC_URL}\n"
            f"最新区块：{latest}\n"
            "监控范围：Uniswap V2/V3/V4 流动性、Swap、跨链资金、地址画像"
        ) if LANGUAGE.lower().startswith("zh") else (
            "✅ Robinhood Chain Radar started\n"
            f"Chain ID: {CHAIN_ID}\n"
            f"Alert threshold: {fmt_usd(ALERT_USD)}\n"
            f"RPC: {RPC_URL}\n"
            f"Latest block: {latest}\n"
            "Watching: Uniswap V2/V3/V4 liquidity, swaps, bridge inflows and address intelligence"
        )
    )

def run():
    latest = healthcheck()
    saved = kv_get("last_block")
    if saved is None:
        last = max(0, latest - START_BACKFILL_BLOCKS)
    else:
        last = int(saved)

    send_startup(latest)
    log.info("Starting from block %s", last + 1)

    failures = 0
    while True:
        try:
            head = rpc.block_number() - CONFIRMATIONS
            if head <= last:
                kv_set("latest_head", str(head))
                kv_set("heartbeat", str(int(time.time())))
                time.sleep(POLL_SECONDS)
                continue

            start = last + 1
            end = min(head, start + BLOCK_CHUNK - 1)

            # One broad topic-filtered log query catches V2/V3 LP events and bridge finalizations.
            logs = rpc.get_logs(start, end)
            for lg in logs:
                process_log(lg)

            # Batch block reads catch native Arbitrum deposit tx type 0x64.
            nums = list(range(start, end + 1))
            blocks = rpc.get_blocks(nums, full=True)
            process_native_deposits(blocks)

            last = end
            kv_set("last_block", str(last))
            kv_set("latest_head", str(head))
            kv_set("heartbeat", str(int(time.time())))
            failures = 0

            if last % 1000 < BLOCK_CHUNK:
                log.info("Synced through block %s | logs=%s", last, len(logs))

        except KeyboardInterrupt:
            log.info("Stopped")
            return
        except Exception as e:
            failures += 1
            delay = min(30, max(2, failures * 2))
            log.exception("Loop error; retry in %ss", delay)
            time.sleep(delay)

def self_test():
    latest = healthcheck()
    eth = get_eth_price()
    print(json.dumps({
        "ok": True,
        "version": RADAR_VERSION,
        "chain_id": CHAIN_ID,
        "latest_block": latest,
        "eth_usd": eth,
        "rpc": RPC_URL,
        "v2_factory": V2_FACTORY,
        "v3_factory": V3_FACTORY,
        "v4_pool_manager": V4_POOL_MANAGER,
        "v4_state_view": V4_STATE_VIEW,
        "v4_position_manager": V4_POSITION_MANAGER,
        "intel_correlation_window_min": INTEL_CORRELATION_WINDOW_MIN,
        "intel_swap_min_usd": INTEL_SWAP_MIN_USD,
        "token_radar_min_event_usd": TOKEN_RADAR_MIN_EVENT_USD,
        "token_signal_min_score": TOKEN_SIGNAL_MIN_SCORE,
        "token_correlation_window_min": TOKEN_CORRELATION_WINDOW_MIN,
        "token_signal_cooldown_min": TOKEN_SIGNAL_COOLDOWN_MIN,
        "l2_gateway_router": L2_GATEWAY_ROUTER,
    }, indent=2))

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    elif "--telegram-test" in sys.argv:
        if not TG_TOKEN or not TG_CHAT_ID:
            print(tr("Telegram 未配置：请在 .env 填写 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID",
                     "Telegram is not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"))
            sys.exit(2)
        telegram(
            (
                f"🔔 Robinhood 链资金雷达 V{RADAR_VERSION} · 测试警报\n"
                "Telegram 推送通道正常。\n"
                f"当前警报门槛：{fmt_usd(ALERT_USD)}"
            ) if LANGUAGE.lower().startswith("zh") else (
                f"🔔 Robinhood Chain Radar V{RADAR_VERSION} · Test Alert\n"
                "Telegram delivery is working.\n"
                f"Current alert threshold: {fmt_usd(ALERT_USD)}"
            )
        )
        print(tr("Telegram 测试消息已发送。", "Telegram test message sent."))
    else:
        run()

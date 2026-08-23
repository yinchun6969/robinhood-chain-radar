#!/usr/bin/env python3
import os, json, time, sqlite3, logging
import monitor

DB_PATH = monitor.DB_PATH
MAX_CHUNK = int(os.getenv("FAST_SCAN_CHUNK", "5000"))
MIN_CHUNK = int(os.getenv("FAST_SCAN_MIN_CHUNK", "100"))
POLL = float(os.getenv("FAST_SCAN_POLL_SECONDS", "0.30"))

SWAP_TOPICS = {
    monitor.TOPIC_V2_SWAP.lower(),
    monitor.TOPIC_V3_SWAP.lower(),
    monitor.TOPIC_V4_SWAP.lower(),
}
BRIDGE_TOPICS = {monitor.TOPIC_DEPOSIT_FINALIZED.lower()}
LP_TOPICS = {
    monitor.TOPIC_V2_MINT.lower(), monitor.TOPIC_V2_BURN.lower(),
    monitor.TOPIC_V3_MINT.lower(), monitor.TOPIC_V3_BURN.lower(),
    monitor.TOPIC_V4_MODIFY_LIQUIDITY.lower(),
}
P90 = {
    monitor.TOPIC_V2_PAIR_CREATED.lower(),
    monitor.TOPIC_V3_POOL_CREATED.lower(),
    monitor.TOPIC_V4_INITIALIZE.lower(),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("fast-scanner")

def dbconn():
    d = sqlite3.connect(DB_PATH, timeout=20)
    d.execute("PRAGMA journal_mode=WAL")
    d.execute("PRAGMA busy_timeout=15000")
    return d

def _columns(d, table):
    return {r[1] for r in d.execute(f"PRAGMA table_info({table})").fetchall()}

def ensure(d):
    d.execute('''CREATE TABLE IF NOT EXISTS raw_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      block_number INTEGER NOT NULL,
      log_index INTEGER NOT NULL,
      tx_hash TEXT NOT NULL,
      topic0 TEXT NOT NULL,
      pool_id TEXT,
      payload TEXT NOT NULL,
      status INTEGER NOT NULL DEFAULT 0,
      attempts INTEGER NOT NULL DEFAULT 0,
      claimed_at INTEGER,
      last_error TEXT,
      created_at INTEGER NOT NULL,
      priority INTEGER NOT NULL DEFAULT 50,
      UNIQUE(tx_hash,log_index)
    )''')
    if "priority" not in _columns(d, "raw_events"):
        d.execute("ALTER TABLE raw_events ADD COLUMN priority INTEGER NOT NULL DEFAULT 50")

    d.execute('''CREATE TABLE IF NOT EXISTS swap_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      block_number INTEGER NOT NULL,
      log_index INTEGER NOT NULL,
      tx_hash TEXT NOT NULL,
      topic0 TEXT NOT NULL,
      pool_id TEXT,
      payload TEXT NOT NULL,
      status INTEGER NOT NULL DEFAULT 0,
      attempts INTEGER NOT NULL DEFAULT 0,
      claimed_at INTEGER,
      last_error TEXT,
      created_at INTEGER NOT NULL,
      prefilter_usd REAL,
      decision TEXT,
      UNIQUE(tx_hash,log_index)
    )''')
    d.execute('''CREATE TABLE IF NOT EXISTS v4_resolve_queue(
      pool_id TEXT PRIMARY KEY,
      requested_block INTEGER NOT NULL,
      status INTEGER NOT NULL DEFAULT 0,
      attempts INTEGER NOT NULL DEFAULT 0,
      last_error TEXT,
      updated_at INTEGER NOT NULL
    )''')
    d.execute('''CREATE TABLE IF NOT EXISTS pipeline_metrics(
      key TEXT PRIMARY KEY,
      value REAL NOT NULL DEFAULT 0,
      updated_at INTEGER NOT NULL DEFAULT 0
    )''')
    d.execute("CREATE INDEX IF NOT EXISTS idx_raw_priority ON raw_events(status,priority DESC,block_number,log_index)")
    d.execute("CREATE INDEX IF NOT EXISTS idx_raw_lane ON raw_events(status,priority,block_number,log_index)")
    d.execute("CREATE INDEX IF NOT EXISTS idx_raw_pool_status ON raw_events(pool_id,status)")
    d.execute("CREATE INDEX IF NOT EXISTS idx_swap_status_block ON swap_events(status,block_number,log_index)")
    d.execute("CREATE INDEX IF NOT EXISTS idx_swap_pool_status ON swap_events(pool_id,status)")
    d.commit()

def kv_get(d, k, default=None):
    r = d.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r[0] if r else default

def kv_set_many(d, pairs):
    d.executemany(
        "INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)",
        [(k, str(v)) for k, v in pairs]
    )

def metric_inc(d, key, amount=1):
    now = int(time.time())
    d.execute('''INSERT INTO pipeline_metrics(key,value,updated_at) VALUES(?,?,?)
                 ON CONFLICT(key) DO UPDATE SET
                   value=value+excluded.value, updated_at=excluded.updated_at''',
              (key, float(amount), now))

def pool_id_for(lg):
    topics = lg.get("topics") or []
    t0 = topics[0].lower() if topics else ""
    if t0 in {
        monitor.TOPIC_V4_INITIALIZE.lower(),
        monitor.TOPIC_V4_MODIFY_LIQUIDITY.lower(),
        monitor.TOPIC_V4_SWAP.lower(),
    } and len(topics) > 1:
        return topics[1].lower()
    return None

def event_priority(topic0):
    if topic0 in BRIDGE_TOPICS:
        return 130
    if topic0 in LP_TOPICS:
        return 120
    if topic0 in P90:
        return 90
    return 50

def insert_logs(d, logs):
    now = int(time.time())
    priority_rows, swap_rows = [], []
    for lg in logs:
        topics = lg.get("topics") or [""]
        t0 = (topics[0] if topics else "").lower()
        base = (
            int(lg.get("blockNumber", "0x0"), 16),
            int(lg.get("logIndex", "0x0"), 16),
            lg.get("transactionHash", ""),
            t0,
            pool_id_for(lg),
            json.dumps(lg, separators=(",", ":")),
            now,
        )
        if t0 in SWAP_TOPICS:
            swap_rows.append(base)
        else:
            priority_rows.append(base + (event_priority(t0),))

    if priority_rows:
        d.executemany('''INSERT OR IGNORE INTO raw_events(
          block_number,log_index,tx_hash,topic0,pool_id,payload,created_at,priority
        ) VALUES(?,?,?,?,?,?,?,?)''', priority_rows)
    if swap_rows:
        d.executemany('''INSERT OR IGNORE INTO swap_events(
          block_number,log_index,tx_hash,topic0,pool_id,payload,created_at
        ) VALUES(?,?,?,?,?,?,?)''', swap_rows)

    metric_inc(d, "scanner_priority_events", len(priority_rows))
    metric_inc(d, "scanner_swap_events", len(swap_rows))
    return len(priority_rows), len(swap_rows)

def main(stop_event=None):
    d = dbconn()
    ensure(d)
    legacy = kv_get(d, "last_block")
    saved = kv_get(d, "fast_scanner_last_block", legacy)
    latest = monitor.rpc.block_number()
    last = int(saved) if saved is not None else max(0, latest - monitor.START_BACKFILL_BLOCKS)
    chunk = MAX_CHUNK
    log.info("V1.2.5 fast scanner start=%s latest=%s chunk=%s", last + 1, latest, chunk)

    while stop_event is None or not stop_event.is_set():
        try:
            t_head = time.monotonic()
            head = monitor.rpc.block_number() - monitor.CONFIRMATIONS
            head_ms = int((time.monotonic() - t_head) * 1000)
            kv_set_many(d, [
                ("fast_scanner_head", head),
                ("fast_scanner_heartbeat", int(time.time())),
                ("fast_scanner_rpc_ms", head_ms),
            ])
            d.commit()

            if head <= last:
                time.sleep(POLL)
                continue

            start = last + 1
            end = min(head, start + chunk - 1)
            t0 = time.monotonic()
            try:
                logs = monitor.rpc.get_logs(start, end)
            except Exception as e:
                metric_inc(d, "scanner_rpc_errors", 1)
                d.commit()
                if chunk > MIN_CHUNK:
                    chunk = max(MIN_CHUNK, chunk // 2)
                    log.warning("eth_getLogs %s-%s failed; chunk -> %s: %s", start, end, chunk, e)
                    time.sleep(0.5)
                    continue
                raise

            pri_n, swap_n = insert_logs(d, logs)
            last = end
            batch_ms = int((time.monotonic() - t0) * 1000)
            kv_set_many(d, [
                ("fast_scanner_last_block", last), ("last_block", last),
                ("fast_scanner_head", head), ("latest_head", head),
                ("fast_scanner_heartbeat", int(time.time())), ("heartbeat", int(time.time())),
                ("fast_scanner_batch_ms", batch_ms), ("fast_scanner_chunk", chunk),
            ])
            d.commit()

            lag = max(0, head - last)
            if chunk < MAX_CHUNK and batch_ms < 5000:
                chunk = min(MAX_CHUNK, max(chunk + MIN_CHUNK, int(chunk * 1.30)))

            if logs or lag > 1000:
                log.info(
                    "scan %s-%s fast=%s swaps=%s lag=%s batch=%sms rpc=%sms chunk=%s",
                    start, end, pri_n, swap_n, lag, batch_ms, head_ms, chunk
                )
        except KeyboardInterrupt:
            return
        except Exception:
            log.exception("Fast scanner error")
            time.sleep(2)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os, sys, json, time, math, sqlite3, logging
import monitor
import fast_scanner

DB_PATH = monitor.DB_PATH
DEFAULT_WORKER_ID = int(os.getenv("SWAP_WORKER_ID") or (sys.argv[1] if len(sys.argv) > 1 else "1"))
MAX_WORKERS = int(os.getenv("SWAP_FILTER_MAX_WORKERS", "3"))
IDLE = float(os.getenv("SWAP_FILTER_IDLE_SECONDS", "0.06"))
BATCH_SIZE = int(os.getenv("SWAP_FILTER_BATCH_SIZE", "24"))
PREFILTER_USD = float(os.getenv("SWAP_PREFILTER_MIN_USD", "80000"))
FINAL_USD = float(os.getenv("INTEL_SWAP_MIN_USD", "100000"))
SHADOW_EVERY = int(os.getenv("SWAP_SHADOW_SAMPLE_EVERY", "200"))

T_V2 = monitor.TOPIC_V2_SWAP.lower()
T_V3 = monitor.TOPIC_V3_SWAP.lower()
T_V4 = monitor.TOPIC_V4_SWAP.lower()
ZERO = "0x0000000000000000000000000000000000000000"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("swap-filter")

def conn():
    d = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    d.execute("PRAGMA journal_mode=WAL")
    d.execute("PRAGMA busy_timeout=15000")
    fast_scanner.ensure(d)
    return d

def kv_get(d, k, default=0):
    r = d.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r[0] if r else default

def kv(d, k, v):
    d.execute("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (k, str(v)))

def metric_inc(d, key, amount=1):
    now = int(time.time())
    d.execute('''INSERT INTO pipeline_metrics(key,value,updated_at) VALUES(?,?,?)
                 ON CONFLICT(key) DO UPDATE SET
                   value=value+excluded.value, updated_at=excluded.updated_at''',
              (key, float(amount), now))

def metric_get(d, key, default=0):
    r = d.execute("SELECT value FROM pipeline_metrics WHERE key=?", (key,)).fetchone()
    return float(r[0]) if r else float(default)

def adaptive_target(rpc_ms, batch_ms=0, backoff_until=0, now=None):
    now = int(time.time()) if now is None else int(now)
    if backoff_until and backoff_until > now:
        return 1
    # Protect the scanner first.
    pressure = max(int(rpc_ms or 0), int(batch_ms or 0) // 4)
    if pressure > 1500:
        return 1
    if pressure > 700:
        return 2
    return 3

def update_target(d):
    rpc_ms = int(float(kv_get(d, "fast_scanner_rpc_ms", 0) or 0))
    batch_ms = int(float(kv_get(d, "fast_scanner_batch_ms", 0) or 0))
    backoff = int(float(kv_get(d, "swap_global_backoff_until", 0) or 0))
    target = min(MAX_WORKERS, adaptive_target(rpc_ms, batch_ms, backoff))
    kv(d, "swap_filter_target_workers", target)
    return target

def claim_batch(d):
    now = int(time.time())
    d.execute("BEGIN IMMEDIATE")
    try:
        rows = d.execute('''SELECT id,payload,topic0,pool_id,block_number
                            FROM swap_events
                            WHERE status=0
                            ORDER BY block_number DESC,log_index DESC,id DESC
                            LIMIT ?''', (BATCH_SIZE,)).fetchall()
        if not rows:
            d.execute("COMMIT")
            return []
        ids = [r[0] for r in rows]
        ph = ",".join("?" for _ in ids)
        d.execute(f"UPDATE swap_events SET status=1,claimed_at=? WHERE id IN ({ph})",
                  (now, *ids))
        d.execute("COMMIT")
        return rows
    except Exception:
        d.execute("ROLLBACK")
        raise

def mark(d, eid, status, decision=None, usd=None, error=None):
    d.execute('''UPDATE swap_events
                 SET status=?,claimed_at=NULL,decision=?,prefilter_usd=?,last_error=?
                 WHERE id=?''',
              (status, decision, usd, str(error)[:500] if error else None, eid))

def retry_or_dead(d, eid, err):
    row = d.execute("SELECT attempts FROM swap_events WHERE id=?", (eid,)).fetchone()
    n = (row[0] if row else 0) + 1
    d.execute('''UPDATE swap_events
                 SET status=?,attempts=?,claimed_at=NULL,last_error=?
                 WHERE id=?''',
              (4 if n >= 4 else 0, n, str(err)[:500], eid))

def maybe_global_backoff(d, err):
    s = str(err).lower()
    if "429" in s or "too many" in s or "rate limit" in s:
        seconds = 12
    elif "timed out" in s or "timeout" in s:
        seconds = 6
    else:
        return
    until = int(time.time()) + seconds
    kv(d, "swap_global_backoff_until", until)
    metric_inc(d, "swap_rpc_backoffs", 1)

def defer_v4(d, eid, pool_id, block):
    if not pool_id:
        return False
    exists = monitor.db.execute("SELECT 1 FROM v4_pools WHERE pool_id=?", (pool_id,)).fetchone()
    if exists:
        return False
    d.execute(
        "INSERT OR IGNORE INTO v4_resolve_queue(pool_id,requested_block,updated_at) VALUES(?,?,?)",
        (pool_id, block, int(time.time()))
    )
    metric_inc(d, "swap_deferred", 1)
    mark(d, eid, 2, "v4-resolve")
    return True

dec_cache = {}
pool_cache = {}

def anchor_price(addr):
    a = monitor.norm(addr)
    if a == monitor.USDG:
        return 1.0, "USDG"
    if a in (monitor.WETH, ZERO, "", "0x0"):
        p = monitor.get_eth_price()
        return (p, "ETH/USD") if p else (None, None)
    return None, None

def get_decimals(addr):
    a = monitor.norm(addr)
    if a in ("", "0x0", ZERO):
        return 18
    if a in dec_cache:
        return dec_cache[a]
    raw = monitor.rpc.eth_call(a, monitor.SEL_DECIMALS)
    d = int(raw, 16)
    if d < 0 or d > 36:
        d = 18
    dec_cache[a] = d
    return d

def pool_info(pool, expected):
    key = (monitor.norm(pool), expected)
    if key in pool_cache:
        return pool_cache[key]
    p = key[0]
    rf, r0, r1 = monitor.rpc.batch([
        ("eth_call", [{"to": p, "data": monitor.SEL_FACTORY}, "latest"]),
        ("eth_call", [{"to": p, "data": monitor.SEL_TOKEN0}, "latest"]),
        ("eth_call", [{"to": p, "data": monitor.SEL_TOKEN1}, "latest"]),
    ])
    factory = "0x" + rf[-40:].lower()
    want = monitor.V2_FACTORY if expected == "v2" else monitor.V3_FACTORY
    if factory != want:
        return None
    a0, a1 = "0x" + r0[-40:].lower(), "0x" + r1[-40:].lower()
    info = (a0, a1, get_decimals(a0), get_decimals(a1))
    pool_cache[key] = info
    return info

def human(raw, decimals):
    return abs(int(raw)) / (10 ** decimals)

def ratio_price(a0, a1, ratio, input_index):
    p0, s0 = anchor_price(a0)
    p1, s1 = anchor_price(a1)
    if input_index == 0:
        if p0 is not None:
            return p0, s0
        if p1 is not None and ratio and ratio > 0:
            return ratio * p1, f"{s1}+pool-spot"
    else:
        if p1 is not None:
            return p1, s1
        if p0 is not None and ratio and ratio > 0:
            return p0 / ratio, f"{s0}+pool-spot"
    return None, None

def v2_estimate(lg):
    pool = monitor.norm(lg["address"])
    info = pool_info(pool, "v2")
    if not info:
        return None, "wrong-pool"
    a0, a1, d0, d1 = info
    x0, x1 = monitor.word(lg["data"], 0), monitor.word(lg["data"], 1)
    if x0 > 0:
        idx, raw, dec = 0, x0, d0
    elif x1 > 0:
        idx, raw, dec = 1, x1, d1
    else:
        return None, "no-input"

    direct, source = anchor_price(a0 if idx == 0 else a1)
    if direct is not None:
        return human(raw, dec) * direct, source

    rr = monitor.rpc.eth_call(pool, monitor.SEL_GET_RESERVES)
    r0, r1 = monitor.word(rr, 0), monitor.word(rr, 1)
    if r0 <= 0 or r1 <= 0:
        return None, "zero-reserve"
    h0, h1 = human(r0, d0), human(r1, d1)
    if h0 <= 0:
        return None, "zero-reserve"
    price, source = ratio_price(a0, a1, h1 / h0, idx)
    if price is None:
        return None, "unanchored"
    return human(raw, dec) * price, source

def v3_estimate(lg):
    pool = monitor.norm(lg["address"])
    info = pool_info(pool, "v3")
    if not info:
        return None, "wrong-pool"
    a0, a1, d0, d1 = info
    x0, x1 = monitor.signed_word(lg["data"], 0), monitor.signed_word(lg["data"], 1)
    if x0 > 0:
        idx, raw, dec = 0, x0, d0
    elif x1 > 0:
        idx, raw, dec = 1, x1, d1
    else:
        return None, "no-input"
    sqrt_p = monitor.word(lg["data"], 2)
    try:
        ratio = (sqrt_p / (2 ** 96)) ** 2 * (10 ** (d0 - d1))
        if ratio <= 0 or not math.isfinite(ratio):
            ratio = None
    except Exception:
        ratio = None
    price, source = ratio_price(a0, a1, ratio, idx)
    if price is None:
        return None, "unanchored"
    return human(raw, dec) * price, source

def v4_estimate(lg, pool_id):
    pool = monitor.v4_get_pool(pool_id)
    if not pool:
        return None, "unresolved"
    a0, a1 = monitor.norm(pool["currency0"]), monitor.norm(pool["currency1"])
    d0, d1 = get_decimals(a0), get_decimals(a1)
    x0, x1 = monitor.signed_word(lg["data"], 0), monitor.signed_word(lg["data"], 1)
    if x0 > 0:
        idx, raw, dec = 0, x0, d0
    elif x1 > 0:
        idx, raw, dec = 1, x1, d1
    else:
        return None, "no-input"
    sqrt_p = monitor.word(lg["data"], 2)
    try:
        ratio = (sqrt_p / (2 ** 96)) ** 2 * (10 ** (d0 - d1))
        if ratio <= 0 or not math.isfinite(ratio):
            ratio = None
    except Exception:
        ratio = None
    price, source = ratio_price(a0, a1, ratio, idx)
    if price is None:
        return None, "unanchored"
    return human(raw, dec) * price, source

def estimate(lg, topic0, pool_id):
    if topic0 == T_V2:
        return v2_estimate(lg)
    if topic0 == T_V3:
        return v3_estimate(lg)
    if topic0 == T_V4:
        return v4_estimate(lg, pool_id)
    return None, "not-swap"

def classify_reason(reason):
    r = str(reason or "unknown").lower()
    if r == "unanchored":
        return "unanchored"
    if r == "wrong-pool":
        return "wrong_pool"
    if r == "no-input":
        return "no_input"
    if r == "zero-reserve":
        return "zero_reserve"
    return "other_unpriced"

def swap_record_exists(d, tx_hash):
    try:
        return bool(d.execute(
            "SELECT 1 FROM address_events WHERE event_type='swap' AND tx_hash=? LIMIT 1",
            (tx_hash,)
        ).fetchone())
    except Exception:
        return False

def shadow_check(d, eid, lg):
    if SHADOW_EVERY <= 0 or eid % SHADOW_EVERY != 0:
        return False
    metric_inc(d, "swap_shadow_checked", 1)
    txh = lg.get("transactionHash", "")
    before = swap_record_exists(d, txh)
    monitor.process_log(lg)  # Full pricing path, including normal fallback sources.
    after = swap_record_exists(d, txh)
    missed = (not before) and after
    if missed:
        metric_inc(d, "swap_shadow_missed", 1)
        metric_inc(d, "swap_confirmed", 1)
    return missed

def main(worker_id=None, stop_event=None):
    worker_id=int(worker_id or DEFAULT_WORKER_ID)
    d = conn()
    d.execute(
        "UPDATE swap_events SET status=0,claimed_at=NULL WHERE status=1 AND claimed_at<?",
        (int(time.time()) - 300,),
    )

    rate_n = 0
    rate_t0 = time.monotonic()
    last_target_update = 0
    log.info(
        "Swap filter %s started; max=%s prefilter=$%s final=$%s shadow=1/%s",
        worker_id, MAX_WORKERS, int(PREFILTER_USD), int(FINAL_USD), SHADOW_EVERY
    )

    while stop_event is None or not stop_event.is_set():
        try:
            now = int(time.time())
            kv(d, f"swap_filter_heartbeat_{worker_id}", now)

            if worker_id == 1 or now - last_target_update >= 3:
                target = update_target(d)
                last_target_update = now
            else:
                target = int(float(kv_get(d, "swap_filter_target_workers", 3) or 3))

            kv(d, f"swap_filter_active_{worker_id}", 1 if worker_id <= target else 0)
            if worker_id > target:
                kv(d, f"swap_filter_rate_{worker_id}", 0)
                time.sleep(0.7)
                continue

            backoff = int(float(kv_get(d, "swap_global_backoff_until", 0) or 0))
            if backoff > now and worker_id > 1:
                kv(d, f"swap_filter_rate_{worker_id}", 0)
                time.sleep(0.7)
                continue

            rows = claim_batch(d)
            if not rows:
                time.sleep(IDLE)
                continue

            for eid, payload, topic0, pool_id, block in rows:
                try:
                    if topic0 == T_V4 and defer_v4(d, eid, pool_id, block):
                        continue

                    lg = json.loads(payload)
                    metric_inc(d, "swap_processed", 1)
                    rate_n += 1
                    usd, reason = estimate(lg, topic0, pool_id)

                    if usd is None:
                        kind = classify_reason(reason)
                        metric_inc(d, f"swap_{kind}", 1)

                        if kind == "unanchored":
                            if shadow_check(d, eid, lg):
                                metric_inc(d, "swap_candidates", 1)
                                mark(d, eid, 3, "shadow-promoted", None)
                                continue
                            mark(d, eid, 3, "discard:unanchored", None)
                        else:
                            mark(d, eid, 3, "discard:" + str(reason), None)
                        continue

                    if usd < PREFILTER_USD:
                        metric_inc(d, "swap_small", 1)
                        mark(d, eid, 3, "discard:small", usd)
                        continue

                    # Candidate passed the cheap filter. Full analyzer still enforces $100K.
                    metric_inc(d, "swap_candidates", 1)
                    txh = lg.get("transactionHash", "")
                    before = swap_record_exists(d, txh)
                    monitor.process_log(lg)
                    after = swap_record_exists(d, txh)

                    if (not before) and after:
                        metric_inc(d, "swap_confirmed", 1)
                        mark(d, eid, 3, "candidate:confirmed", usd)
                    else:
                        metric_inc(d, "swap_candidate_rejected", 1)
                        mark(d, eid, 3, "candidate:below-final", usd)

                except Exception as e:
                    metric_inc(d, "swap_errors", 1)
                    maybe_global_backoff(d, e)
                    retry_or_dead(d, eid, e)
                    log.warning("swap event %s failed: %s", eid, e)

            elapsed = time.monotonic() - rate_t0
            if elapsed >= 3:
                kv(d, f"swap_filter_rate_{worker_id}", round(rate_n / elapsed, 2))
                kv(d, f"swap_filter_heartbeat_{worker_id}", int(time.time()))
                rate_n = 0
                rate_t0 = time.monotonic()

        except KeyboardInterrupt:
            return
        except Exception as e:
            metric_inc(d, "swap_errors", 1)
            maybe_global_backoff(d, e)
            log.exception("Swap filter %s loop error", worker_id)
            time.sleep(1)

if __name__ == "__main__":
    main()

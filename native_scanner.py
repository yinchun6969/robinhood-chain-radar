#!/usr/bin/env python3
import os, time, sqlite3, logging
import monitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("native-scanner")

HISTORY_WINDOW = int(os.getenv("NATIVE_HISTORY_WINDOW_BLOCKS", "1000"))
FAST_FORWARD = os.getenv("NATIVE_FAST_FORWARD_ON_START", "1").lower() not in ("0","false","no")

def kv_get(d, k, default=None):
    r = d.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r[0] if r else default

def kv(d, k, v):
    d.execute("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)", (k, str(v)))

def desired_chunk(lag, scanner_rpc_ms):
    # Native is lower priority than realtime logs.
    if scanner_rpc_ms > 1500:
        return 20
    if scanner_rpc_ms > 700:
        return 40
    if lag > 2000:
        return 160
    if lag > 500:
        return 90
    return 40

def main(stop_event=None):
    d = sqlite3.connect(monitor.DB_PATH, timeout=20)
    d.execute("PRAGMA journal_mode=WAL")
    d.execute("PRAGMA busy_timeout=15000")

    legacy = kv_get(d, "fast_scanner_last_block", kv_get(d, "last_block"))
    saved = kv_get(d, "native_scanner_last_block", legacy)
    head = monitor.rpc.block_number() - monitor.CONFIRMATIONS
    last = int(saved) if saved else max(0, head - monitor.START_BACKFILL_BLOCKS)

    lag = max(0, head - last)
    if FAST_FORWARD and lag > HISTORY_WINDOW:
        old = last
        last = max(0, head - HISTORY_WINDOW)
        kv(d, "native_scanner_last_block", last)
        d.commit()
        log.warning("Native fast-forward %s -> %s (old lag=%s keep=%s)", old, last, lag, HISTORY_WINDOW)

    log.info("Native V1.2.3 start=%s head=%s", last + 1, head)

    while stop_event is None or not stop_event.is_set():
        try:
            head = monitor.rpc.block_number() - monitor.CONFIRMATIONS
            scanner_rpc = int(float(kv_get(d, "fast_scanner_rpc_ms", 0) or 0))
            lag = max(0, head - last)
            chunk = desired_chunk(lag, scanner_rpc)

            kv(d, "native_scanner_head", head)
            kv(d, "native_scanner_heartbeat", int(time.time()))
            kv(d, "native_scanner_chunk", chunk)
            d.commit()

            if head <= last:
                time.sleep(0.8)
                continue

            start = last + 1
            end = min(head, start + chunk - 1)
            nums = list(range(start, end + 1))
            t0 = time.monotonic()

            try:
                blocks = monitor.rpc.get_blocks(nums, full=True)
            except Exception as e:
                log.warning("Native block batch %s-%s failed: %s", start, end, e)
                time.sleep(1.2)
                continue

            deposits = []
            tx_count = 0
            for b in blocks:
                if not b:
                    continue
                txs = b.get("transactions") or []
                tx_count += len(txs)
                selected = [
                    tx for tx in txs
                    if str(tx.get("type","")).lower() in ("0x64","0x064")
                ]
                if selected:
                    deposits.append({"number": b.get("number"), "transactions": selected})

            if deposits:
                monitor.process_native_deposits(deposits)

            last = end
            kv(d, "native_scanner_last_block", last)
            kv(d, "native_scanner_head", head)
            kv(d, "native_scanner_heartbeat", int(time.time()))
            kv(d, "native_scanner_batch_ms", int((time.monotonic()-t0)*1000))
            d.commit()

            new_lag = max(0, head - last)
            if deposits or new_lag > 500:
                dep_count = sum(len(x["transactions"]) for x in deposits)
                log.info(
                    "Native %s-%s tx=%s deposits=%s lag=%s chunk=%s scanner_rpc=%sms",
                    start, end, tx_count, dep_count, new_lag, chunk, scanner_rpc
                )
            # Yield to the realtime scanner / swap filters.
            time.sleep(0.08 if scanner_rpc < 700 else 0.35)

        except KeyboardInterrupt:
            return
        except Exception:
            log.exception("Native scanner error")
            time.sleep(2)

if __name__ == "__main__":
    main()

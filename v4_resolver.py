#!/usr/bin/env python3
import time, sqlite3, logging
import monitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("v4-resolver")

def main(stop_event=None):
    d = sqlite3.connect(monitor.DB_PATH, timeout=20, isolation_level=None)
    d.execute("PRAGMA journal_mode=WAL")
    d.execute("PRAGMA busy_timeout=15000")

    while stop_event is None or not stop_event.is_set():
        try:
            d.execute("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)",
                      ("resolver_heartbeat", str(int(time.time()))))
            row = d.execute('''SELECT pool_id,requested_block,attempts
                               FROM v4_resolve_queue
                               WHERE status=0 ORDER BY updated_at LIMIT 1''').fetchone()
            if not row:
                time.sleep(0.7)
                continue

            pool_id, block, attempts = row
            d.execute("UPDATE v4_resolve_queue SET status=1,updated_at=? WHERE pool_id=?",
                      (int(time.time()), pool_id))
            try:
                pool = monitor.v4_find_pool_init(pool_id, block)
                if pool:
                    d.execute("DELETE FROM v4_resolve_queue WHERE pool_id=?", (pool_id,))
                    d.execute("UPDATE raw_events SET status=0 WHERE status=2 AND pool_id=?", (pool_id,))
                    d.execute("UPDATE swap_events SET status=0 WHERE status=2 AND pool_id=?", (pool_id,))
                    log.info("Resolved V4 pool %s", pool_id)
                else:
                    d.execute('''UPDATE v4_resolve_queue
                                 SET status=2,attempts=attempts+1,last_error=?,updated_at=?
                                 WHERE pool_id=?''',
                              ("not found", int(time.time()), pool_id))
            except Exception as e:
                status = 2 if attempts >= 2 else 0
                d.execute('''UPDATE v4_resolve_queue
                             SET status=?,attempts=attempts+1,last_error=?,updated_at=?
                             WHERE pool_id=?''',
                          (status, str(e)[:500], int(time.time()), pool_id))
                log.warning("Resolver failed %s: %s", pool_id, e)
                time.sleep(1)

        except KeyboardInterrupt:
            return
        except Exception:
            log.exception("Resolver loop error")
            time.sleep(2)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os, sys, json, time, sqlite3, logging
import monitor

DB_PATH = monitor.DB_PATH
DEFAULT_WORKER_ID = os.getenv("WORKER_ID") or (sys.argv[1] if len(sys.argv) > 1 else "1")
DEFAULT_MODE = (os.getenv("WORKER_MODE") or (sys.argv[2] if len(sys.argv) > 2 else "fast")).lower()
IDLE = float(os.getenv("WORKER_IDLE_SECONDS", "0.10"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("event-worker")

def conn():
    d = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    d.execute("PRAGMA journal_mode=WAL")
    d.execute("PRAGMA busy_timeout=15000")
    return d

def kv(d,k,v):
    d.execute("INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)",(k,str(v)))

def lane_where(mode):
    return "priority>=120" if mode=="fast" else "priority<120"

def claim_for_mode(d,mode):
    now=int(time.time())
    where=lane_where(mode)
    order = "priority DESC,block_number DESC,log_index DESC,id DESC" if mode=="fast" else "priority DESC,block_number,log_index,id"
    d.execute("BEGIN IMMEDIATE")
    try:
        row=d.execute(f"""SELECT id,payload,topic0,pool_id,block_number,priority
                          FROM raw_events WHERE status=0 AND {where}
                          ORDER BY {order} LIMIT 1""").fetchone()
        if not row:
            d.execute("COMMIT"); return None
        d.execute("UPDATE raw_events SET status=1,claimed_at=? WHERE id=?",(now,row[0]))
        d.execute("COMMIT"); return row
    except Exception:
        d.execute("ROLLBACK"); raise

def defer_v4(d,row):
    eid,payload,topic0,pool_id,block,priority=row
    if not pool_id or topic0!=monitor.TOPIC_V4_MODIFY_LIQUIDITY.lower():
        return False
    exists=monitor.db.execute("SELECT 1 FROM v4_pools WHERE pool_id=?",(pool_id,)).fetchone()
    if exists:return False
    d.execute("INSERT OR IGNORE INTO v4_resolve_queue(pool_id,requested_block,updated_at) VALUES(?,?,?)",
              (pool_id,block,int(time.time())))
    d.execute("UPDATE raw_events SET status=2,claimed_at=NULL WHERE id=?",(eid,))
    return True

def mark_done(d,eid):
    d.execute("UPDATE raw_events SET status=3,claimed_at=NULL,last_error=NULL WHERE id=?",(eid,))

def mark_error(d,eid,err):
    row=d.execute("SELECT attempts FROM raw_events WHERE id=?",(eid,)).fetchone()
    n=(row[0] if row else 0)+1
    d.execute("UPDATE raw_events SET status=?,attempts=?,claimed_at=NULL,last_error=? WHERE id=?",
              (4 if n>=5 else 0,n,str(err)[:500],eid))

def main(worker_id=None, mode=None, stop_event=None):
    worker_id=str(worker_id or DEFAULT_WORKER_ID)
    mode=(mode or DEFAULT_MODE).lower()
    if mode not in ("fast","meta"):
        raise ValueError("mode must be fast or meta")
    d=conn()
    d.execute(f"UPDATE raw_events SET status=0,claimed_at=NULL WHERE status=1 AND {lane_where(mode)} AND claimed_at<?",
              (int(time.time())-300,))
    processed=0; rate_n=0; rate_t=time.monotonic()
    hb=f"worker_heartbeat_{mode}_{worker_id}"
    ratekey=f"worker_rate_{mode}_{worker_id}"
    logger=logging.getLogger(f"{mode}-worker-{worker_id}")
    logger.info("%s worker %s started",mode,worker_id)

    while stop_event is None or not stop_event.is_set():
        eid=None
        try:
            kv(d,hb,int(time.time()))
            row=claim_for_mode(d,mode)
            if not row:
                time.sleep(IDLE); continue
            eid,payload,topic0,pool_id,block,priority=row
            if mode=="fast" and defer_v4(d,row):
                continue
            lg=json.loads(payload)
            monitor.process_log(lg)
            mark_done(d,eid)

            if topic0==monitor.TOPIC_V4_INITIALIZE.lower() and pool_id:
                d.execute("UPDATE raw_events SET status=0 WHERE status=2 AND pool_id=?",(pool_id,))
                d.execute("UPDATE swap_events SET status=0 WHERE status=2 AND pool_id=?",(pool_id,))
                d.execute("DELETE FROM v4_resolve_queue WHERE pool_id=?",(pool_id,))

            processed+=1; rate_n+=1
            kv(d,hb,int(time.time()))
            kv(d,f"worker_processed_{mode}_{worker_id}",processed)
            elapsed=time.monotonic()-rate_t
            if elapsed>=4:
                kv(d,ratekey,round(rate_n/elapsed,3))
                rate_n=0; rate_t=time.monotonic()
        except Exception as e:
            logger.exception("%s worker error",mode)
            if eid is not None:
                try:mark_error(d,eid,e)
                except Exception:pass
            time.sleep(1)

if __name__=="__main__":
    main()

#!/usr/bin/env python3
import os
import sys
import time
import sqlite3
import threading
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP=Path(__file__).resolve().parent
LOG=APP/'supervisor.log'
DB=Path(os.getenv('DB_PATH', str(APP/'radar.db'))).expanduser()

root=logging.getLogger()
root.setLevel(logging.INFO)
if not root.handlers:
    handler=RotatingFileHandler(LOG,maxBytes=8*1024*1024,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(threadName)s | %(message)s'))
    root.addHandler(handler)
log=logging.getLogger('supervisor')

# Import after logging setup so every component shares the rotating handler.
import monitor
import fast_scanner
import event_worker
import swap_filter
import v4_resolver
import native_scanner
import token_worker
import dashboard

EXPECTED_COMPONENTS = {
    'fast-scanner': lambda stop: fast_scanner.main(stop),
    'fast-1': lambda stop: event_worker.main('1','fast',stop),
    'fast-2': lambda stop: event_worker.main('2','fast',stop),
    'meta-1': lambda stop: event_worker.main('1','meta',stop),
    'swap-1': lambda stop: swap_filter.main(1,stop),
    'swap-2': lambda stop: swap_filter.main(2,stop),
    'swap-3': lambda stop: swap_filter.main(3,stop),
    'v4-resolver': lambda stop: v4_resolver.main(stop),
    'native-scanner': lambda stop: native_scanner.main(stop),
    'token-radar': lambda stop: token_worker.main(stop),
    'dashboard': lambda stop: dashboard.run_server(),
}

STARTED=int(time.time())
STALE_SEC=int(os.getenv('SUPERVISOR_SCANNER_STALE_SEC','180'))
MAX_RSS_MB=int(os.getenv('SUPERVISOR_MAX_RSS_MB','700'))
MAINT_INTERVAL=int(os.getenv('MAINTENANCE_INTERVAL_SEC','60'))
SWAP_BACKLOG_MAX=int(os.getenv('SWAP_BACKLOG_MAX','50000'))
SWAP_MAX_AGE_MIN=int(os.getenv('SWAP_MAX_AGE_MIN','30'))
FAST_MAX_AGE_MIN=int(os.getenv('FAST_MAX_AGE_MIN','30'))

stop_event=threading.Event()
threads={}
restart_counts={k:0 for k in EXPECTED_COMPONENTS}
lock=threading.RLock()

def dbconn():
    d=sqlite3.connect(DB,timeout=20,isolation_level=None)
    d.execute('PRAGMA journal_mode=WAL')
    d.execute('PRAGMA busy_timeout=15000')
    return d

def kv(d,k,v):
    d.execute('INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)',(k,str(v)))

def metric_inc(d,key,amount=1):
    now=int(time.time())
    d.execute('''INSERT INTO pipeline_metrics(key,value,updated_at) VALUES(?,?,?)
                 ON CONFLICT(key) DO UPDATE SET value=value+excluded.value,updated_at=excluded.updated_at''',
              (key,float(amount),now))

def component_wrapper(name,target):
    while not stop_event.is_set():
        try:
            log.info('component start: %s',name)
            target(stop_event)
            if stop_event.is_set():
                return
            log.warning('component returned unexpectedly: %s',name)
        except Exception:
            log.exception('component crashed: %s',name)
        with lock:
            restart_counts[name]+=1
        time.sleep(min(10,1+restart_counts[name]))

def spawn(name):
    t=threading.Thread(target=component_wrapper,args=(name,EXPECTED_COMPONENTS[name]),name=name,daemon=True)
    threads[name]=t
    t.start()

def rss_mb():
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return float(line.split()[1])/1024.0
    except Exception:
        pass
    return 0.0

def expire_backlogs(d, now=None):
    now=int(now or time.time())

    # Swap intelligence is realtime-first. Preserve a bounded recent window.
    cutoff=now-SWAP_MAX_AGE_MIN*60
    cur=d.execute("UPDATE swap_events SET status=5,decision='expired:age',claimed_at=NULL WHERE status=0 AND created_at<?",(cutoff,))
    if cur.rowcount and cur.rowcount>0:
        metric_inc(d,'swap_expired',cur.rowcount)

    pending=d.execute('SELECT COUNT(*) FROM swap_events WHERE status=0').fetchone()[0]
    if pending>SWAP_BACKLOG_MAX:
        n=pending-SWAP_BACKLOG_MAX
        ids=[r[0] for r in d.execute('SELECT id FROM swap_events WHERE status=0 ORDER BY block_number,log_index,id LIMIT ?',(n,)).fetchall()]
        if ids:
            ph=','.join('?' for _ in ids)
            d.execute(f"UPDATE swap_events SET status=5,decision='expired:cap',claimed_at=NULL WHERE id IN ({ph})",ids)
            metric_inc(d,'swap_expired',len(ids))

    # Never expire canonical bridge priority 130. Only stale LP priority 120.
    fast_cutoff=now-FAST_MAX_AGE_MIN*60
    cur=d.execute("UPDATE raw_events SET status=5,last_error='expired:age',claimed_at=NULL WHERE status=0 AND priority=120 AND created_at<?",(fast_cutoff,))
    if cur.rowcount and cur.rowcount>0:
        metric_inc(d,'fast_expired',cur.rowcount)

def maintenance_once(d, now=None):
    """Run one bounded maintenance pass. Kept separate for offline CI tests."""
    now=int(now or time.time())
    expire_backlogs(d, now)
    d.execute('''DELETE FROM raw_events WHERE status IN (3,5) AND id <
                 COALESCE((SELECT MAX(id)-50000 FROM raw_events),0)''')
    d.execute('''DELETE FROM swap_events WHERE status IN (3,5) AND id <
                 COALESCE((SELECT MAX(id)-60000 FROM swap_events),0)''')
    # Token Radar scores a rolling 24h window. Keep seven days of raw token
    # events and thirty days of emitted signals for local forensic review.
    d.execute("DELETE FROM token_events WHERE ts<?", (now-7*86400,))
    d.execute("DELETE FROM token_signals WHERE ts<?", (now-30*86400,))
    # Completed/failed queue rows are disposable; a future event re-enqueues
    # the token. This prevents the primary-key queue from growing forever.
    d.execute("DELETE FROM token_scan_queue WHERE status IN (2,3) AND updated_at<?", (now-7*86400,))
    try:
        d.commit()
    except Exception:
        pass
    d.execute('PRAGMA wal_checkpoint(PASSIVE)')
    size=DB.stat().st_size/(1024*1024) if DB.exists() else 0
    kv(d,'maintenance_db_mb',round(size,2))
    kv(d,'maintenance_heartbeat',now)

def maintenance_loop():
    d=dbconn()
    while not stop_event.is_set():
        try:
            maintenance_once(d)
        except Exception:
            log.exception('maintenance error')
        stop_event.wait(MAINT_INTERVAL)

def self_restart(d,reason):
    old=d.execute("SELECT v FROM kv WHERE k='supervisor_self_restarts'").fetchone()
    count=int(old[0]) if old else 0
    kv(d,'supervisor_self_restarts',count+1)
    kv(d,'supervisor_last_restart_reason',reason)
    log.error('%s -> supervisor self-exec',reason)
    os.execv(sys.executable,[sys.executable,str(Path(__file__).resolve())])

def supervisor_health():
    d=dbconn()
    kv(d,'supervisor_started_at',STARTED)
    while not stop_event.is_set():
        try:
            now=int(time.time())
            live=sum(1 for t in threads.values() if t.is_alive())
            total_restarts=sum(restart_counts.values())
            kv(d,'supervisor_heartbeat',now)
            kv(d,'supervisor_threads_live',live)
            kv(d,'supervisor_threads_expected',len(EXPECTED_COMPONENTS)+2)
            kv(d,'supervisor_component_restarts',total_restarts)
            mem=rss_mb()
            kv(d,'supervisor_rss_mb',round(mem,2))

            row=d.execute("SELECT v FROM kv WHERE k='fast_scanner_heartbeat'").fetchone()
            scanner_hb=int(row[0]) if row else 0
            age=now-scanner_hb if scanner_hb else 0
            if now-STARTED>STALE_SEC and scanner_hb and age>STALE_SEC:
                self_restart(d,f'scanner stale {age}s')
            if MAX_RSS_MB>0 and mem>MAX_RSS_MB and now-STARTED>300:
                self_restart(d,f'rss {mem:.0f}MB')
        except Exception:
            log.exception('supervisor health error')
        stop_event.wait(3)

def main():
    log.info('Robinhood Chain Radar V1.3.0 supervisor starting pid=%s',os.getpid())
    d=dbconn()
    fast_scanner.ensure(d)
    try:
        d.execute('UPDATE raw_events SET status=0,claimed_at=NULL WHERE status=1')
        d.execute('UPDATE swap_events SET status=0,claimed_at=NULL WHERE status=1')
    except Exception:
        pass

    for name in EXPECTED_COMPONENTS:
        spawn(name)

    maintenance=threading.Thread(target=maintenance_loop,name='maintenance',daemon=True)
    maintenance.start(); threads['maintenance']=maintenance
    health=threading.Thread(target=supervisor_health,name='supervisor-health',daemon=True)
    health.start(); threads['supervisor-health']=health

    try:
        while True:
            time.sleep(30)
            for name in EXPECTED_COMPONENTS:
                t=threads.get(name)
                if t is None or not t.is_alive():
                    with lock:
                        restart_counts[name]+=1
                    log.warning('wrapper dead, respawn: %s',name)
                    spawn(name)
    except KeyboardInterrupt:
        stop_event.set()
        log.info('Supervisor stopping')

if __name__=='__main__':
    main()

#!/usr/bin/env python3
import os
import sys
import json
import sqlite3
import platform
from pathlib import Path

import requests
from rpc_pool import FailoverRPC

APP = Path(__file__).resolve().parent


def load_dotenv():
    p = APP / '.env'
    if not p.exists():
        return
    for raw in p.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_dotenv()


def urls():
    primary = os.getenv('RADAR_PRIMARY_RPC', '').strip() or os.getenv(
        'RH_RPC_URL', 'https://rpc.mainnet.chain.robinhood.com'
    ).strip()
    xs = [x.strip() for x in os.getenv('RH_RPC_URLS', '').split(',') if x.strip()]
    out = []
    for x in [primary] + xs:
        if x and x not in out and '127.0.0.1:' not in x and 'localhost:' not in x:
            out.append(x)
    return out


def main():
    rows = []
    add = lambda status, name, detail='': rows.append(
        {'status': status, 'name': name, 'detail': str(detail)}
    )

    add('OK' if sys.version_info >= (3, 10) else 'FAIL', 'Python', platform.python_version())

    rpc_urls = urls()
    if not rpc_urls:
        add('FAIL', 'RPC configuration', 'no upstream RPC configured')
    else:
        pool = FailoverRPC(rpc_urls, failback_sec=int(os.getenv('RPC_FAILBACK_SEC', '300')))
        probes = pool.probe_all(5)
        good = [x for x in probes if x.get('ok') and x.get('chain_id') == 4663]
        for x in probes:
            add(
                'OK' if x.get('ok') and x.get('chain_id') == 4663 else 'WARN',
                'RPC',
                f"{x.get('label')} · {x.get('latency_ms', '?')}ms · chain {x.get('chain_id', '?')}",
            )
        if not good:
            add('FAIL', 'RPC failover', 'no healthy Chain 4663 endpoint')
        elif len(rpc_urls) < 2:
            add('WARN', 'RPC redundancy', 'only one upstream configured')
        else:
            add('OK', 'RPC redundancy', f'{len(good)}/{len(rpc_urls)} healthy')

    db = Path(os.getenv('DB_PATH', str(APP / 'radar.db'))).expanduser()
    try:
        d = sqlite3.connect(db, timeout=5)
        integ = d.execute('PRAGMA integrity_check').fetchone()[0]
        add('OK' if integ == 'ok' else 'FAIL', 'SQLite', f'{db} · {integ}')
        tables = {r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        add('OK' if 'token_events' in tables else 'WARN', 'Token schema', 'initialized' if 'token_events' in tables else 'not initialized')
        if 'kv' in tables:
            row = d.execute("SELECT v FROM kv WHERE k='fast_scanner_heartbeat'").fetchone()
            if row:
                import time
                age = max(0, int(time.time()) - int(row[0]))
                add('OK' if age <= int(os.getenv('SUPERVISOR_SCANNER_STALE_SEC', '180')) else 'WARN', 'Fast scanner heartbeat', f'{age}s ago')
            row = d.execute("SELECT v FROM kv WHERE k='lp_rug_heartbeat'").fetchone()
            if row:
                import time
                age = max(0, int(time.time()) - int(row[0]))
                add('OK' if age <= 180 else 'WARN', 'LP Rug worker heartbeat', f'{age}s ago')
        d.close()
    except Exception as e:
        add('FAIL', 'SQLite', e)

    try:
        r = requests.get(f"http://127.0.0.1:{os.getenv('DASHBOARD_PORT', '8787')}/api/health", timeout=2)
        add('OK' if r.ok else 'WARN', 'Dashboard', r.status_code)
    except Exception:
        add('WARN', 'Dashboard', 'not running')

    try:
        r = requests.get(f"http://127.0.0.1:{os.getenv('RPC_PROXY_PORT', '18766')}/health", timeout=2)
        add('OK' if r.ok else 'WARN', 'RPC proxy', r.status_code)
    except Exception:
        add('WARN', 'RPC proxy', 'not running (start via launcher.py)')

    tg_token = bool(os.getenv('TELEGRAM_BOT_TOKEN', '').strip())
    tg_chat = bool(os.getenv('TELEGRAM_CHAT_ID', '').strip())
    add('OK' if tg_token and tg_chat else 'WARN', 'Telegram config', 'configured' if tg_token and tg_chat else 'token/chat id incomplete')

    try:
        r = requests.get('https://robinhoodchain.blockscout.com/api/v2/stats', timeout=4)
        add('OK' if r.ok else 'WARN', 'Blockscout', r.status_code)
    except Exception:
        add('WARN', 'Blockscout', 'unreachable')

    fails = sum(x['status'] == 'FAIL' for x in rows)
    warns = sum(x['status'] == 'WARN' for x in rows)
    result = {
        'version': '1.3.1',
        'status': 'FAIL' if fails else 'WARN' if warns else 'HEALTHY',
        'checks': rows,
    }

    if '--json' in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print('Robinhood Chain Radar Doctor V1.3.1')
        print('=' * 60)
        for x in rows:
            print(f"[{x['status']}] {x['name']}: {x['detail']}")
        print('=' * 60)
        print('STATUS:', result['status'])

    raise SystemExit(1 if fails else 0)


if __name__ == '__main__':
    main()

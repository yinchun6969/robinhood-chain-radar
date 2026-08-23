#!/usr/bin/env python3
"""Offline V1.3.1 regression tests. No live RPC or Telegram calls are made."""
import os
import sqlite3
import tempfile
from pathlib import Path

import requests

from rpc_pool import FailoverRPC
import launcher


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


class FakeSession:
    def post(self, url, json=None, timeout=None):
        if 'bad.example' in url:
            raise requests.ConnectionError('simulated primary failure')
        if isinstance(json, list):
            out = []
            for item in json:
                method = item['method']
                result = '0x1237' if method == 'eth_chainId' else '0x100' if method == 'eth_blockNumber' else None
                out.append({'jsonrpc': '2.0', 'id': item['id'], 'result': result})
            return FakeResponse(out)
        result = '0x1237' if json['method'] == 'eth_chainId' else '0x100'
        return FakeResponse({'jsonrpc': '2.0', 'id': json['id'], 'result': result})


def test_rpc_failover():
    pool = FailoverRPC(
        ['https://bad.example/private/key?secret=1', 'https://good.example/v2/APIKEY'],
        failback_sec=300,
        session_factory=FakeSession,
    )
    assert pool.call('eth_chainId', []) == '0x1237'
    assert pool.active_index == 1
    assert pool.active_label == 'https://good.example'
    # Endpoint labels must never expose provider paths, tokens or query strings.
    assert 'private' not in pool.safe_label(pool.urls[0])
    assert 'secret' not in pool.safe_label(pool.urls[0])
    assert 'APIKEY' not in pool.safe_label(pool.urls[1])


def test_launcher_preserves_primary():
    old = dict(os.environ)
    try:
        os.environ['RADAR_PRIMARY_RPC'] = 'https://primary.example/key'
        os.environ['RH_RPC_URL'] = 'http://127.0.0.1:18766'
        os.environ['RH_RPC_URLS'] = 'https://backup.example/a,https://backup2.example/b'
        got = launcher.upstreams()
        assert got[0] == 'https://primary.example/key'
        assert 'http://127.0.0.1:18766' not in got
        assert len(got) == 3
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_lp_rug_logic():
    with tempfile.TemporaryDirectory() as td:
        os.environ['DB_PATH'] = str(Path(td) / 'radar.db')
        import lp_rug

        assert lp_rug.classify(1_000_000, None) == 'P0'
        assert lp_rug.classify(600_000, None) == 'P1'
        assert lp_rug.classify(300_000, 60) == 'P0'
        assert lp_rug.classify(300_000, 35) == 'P1'
        assert lp_rug.classify(300_000, 10) is None

        d = sqlite3.connect(':memory:')
        d.execute('''CREATE TABLE kv(k TEXT PRIMARY KEY,v TEXT)''')
        d.execute('''CREATE TABLE token_events(
          id INTEGER PRIMARY KEY,ts INTEGER,token TEXT,symbol TEXT,event_type TEXT,
          action TEXT,usd REAL,actor TEXT,pool TEXT,protocol TEXT,tx_hash TEXT,
          block_number INTEGER,metadata TEXT
        )''')
        lp_rug.ensure(d)
        now = 2_000_000_000
        token = '0x' + '1' * 40
        pool = '0x' + '2' * 40
        d.execute("INSERT INTO token_events VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (now-100, token, 'TST', 'liquidity', 'ADD', 2_000_000, '', pool, 'Uniswap V3', '0xadd', 1, '{}'))
        d.execute("INSERT INTO token_events VALUES(2,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (now, token, 'TST', 'liquidity', 'REMOVE', 1_200_000, '', pool, 'Uniswap V3', '0xremove', 2, '{}'))
        baseline = lp_rug._rolling_baseline(d, 2, now, token, pool)
        assert baseline == 2_000_000
        assert lp_rug.classify(1_200_000, 1_200_000 / baseline * 100) == 'P0'

        # Historical seeding must not emit Telegram/save_alert calls.
        old_tg, old_save = lp_rug.monitor.telegram, lp_rug.monitor.save_alert
        lp_rug.monitor.telegram = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('historical Telegram replay'))
        lp_rug.monitor.save_alert = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('historical alert replay'))
        try:
            row = d.execute("SELECT id,ts,token,symbol,action,usd,pool,protocol,tx_hash,block_number FROM token_events WHERE id=2").fetchone()
            lp_rug._process_row(d, row, allow_alert=False)
        finally:
            lp_rug.monitor.telegram, lp_rug.monitor.save_alert = old_tg, old_save
        d.close()


def main():
    test_rpc_failover()
    test_launcher_preserves_primary()
    test_lp_rug_logic()
    print('V1.3.1 regression: OK')


if __name__ == '__main__':
    main()

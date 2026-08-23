#!/usr/bin/env python3
"""LP withdrawal-risk worker using Radar-observed large-liquidity flow baselines.

The percentage is deliberately labelled an observed-flow ratio. It is not exact
pool TVL, and V4 liquidity USD remains the principal estimate produced by Radar.
"""
import os
import time
import sqlite3
import logging

import monitor

log = logging.getLogger('lp-rug')
ABS = float(os.getenv('LP_RUG_ABSOLUTE_USD', '1000000'))
MIN = float(os.getenv('LP_RUG_MIN_REMOVE_USD', '250000'))
P0 = float(os.getenv('LP_RUG_P0_DRAIN_PCT', '50'))
P1 = float(os.getenv('LP_RUG_P1_DRAIN_PCT', '30'))
BASE = float(os.getenv('LP_RUG_BASELINE_MIN_USD', '500000'))
WINDOW = max(1, int(os.getenv('LP_RUG_WINDOW_HOURS', '24'))) * 3600
COOL = int(os.getenv('LP_RUG_COOLDOWN_MIN', '15')) * 60


def ensure(d):
    d.execute('''CREATE TABLE IF NOT EXISTS pool_flow_state(
      pool TEXT NOT NULL, token TEXT NOT NULL, symbol TEXT, protocol TEXT,
      observed_add_usd REAL NOT NULL DEFAULT 0,
      observed_remove_usd REAL NOT NULL DEFAULT 0,
      observed_net_usd REAL NOT NULL DEFAULT 0,
      last_remove_usd REAL NOT NULL DEFAULT 0,
      last_drain_pct REAL,
      last_event_ts INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(pool,token)
    )''')
    d.execute('''CREATE TABLE IF NOT EXISTS lp_rug_signals(
      k TEXT PRIMARY KEY, ts INTEGER NOT NULL, level TEXT NOT NULL
    )''')
    d.commit()


def classify(usd, pct):
    usd = float(usd or 0)
    if usd < MIN:
        return None
    if usd >= ABS or (pct is not None and pct >= P0):
        return 'P0'
    if usd >= max(MIN, ABS * 0.5) or (pct is not None and pct >= P1):
        return 'P1'
    return None


def alert_text(level, symbol, token, pool, usd, pct, protocol, zh):
    ratio = f'{pct:.1f}%' if pct is not None else '—'
    hours = max(1, WINDOW // 3600)
    if zh:
        return (
            f"🔴 {level} · LP 大规模撤出风险\n"
            f"代币：{symbol or 'UNKNOWN'}\nCA：{token}\n协议：{protocol}\n"
            f"本次撤池：${usd:,.0f}\n近{hours}h观察基线撤出比例：{ratio}\n池：{pool}\n"
            "说明：比例基于 Radar 已观察到的大额 LP 净流，不代表精确 TVL；"
            "V4 金额为本金估算。"
        )
    return (
        f"🔴 {level} · Large LP Withdrawal Risk\n"
        f"Token: {symbol or 'UNKNOWN'}\nCA: {token}\nProtocol: {protocol}\n"
        f"Removal: ${usd:,.0f}\nObserved-flow drain ratio ({hours}h): {ratio}\nPool: {pool}\n"
        "Note: ratio uses Radar-observed large-LP net flow, not exact TVL; "
        "V4 amounts are principal estimates."
    )


def _kv(d, key, value):
    d.execute('INSERT OR REPLACE INTO kv(k,v) VALUES(?,?)', (key, str(value)))


def _rolling_baseline(d, event_id, ts, token, pool):
    """Observed large-LP net flow before this event, inside the configured window."""
    cutoff = int(ts or time.time()) - WINDOW
    row = d.execute('''
      SELECT COALESCE(SUM(CASE
        WHEN UPPER(action)='ADD' THEN COALESCE(usd,0)
        WHEN UPPER(action)='REMOVE' THEN -COALESCE(usd,0)
        ELSE 0 END),0)
      FROM token_events
      WHERE event_type='liquidity' AND token=? AND pool=? AND id<? AND ts>=?
    ''', (token, pool, int(event_id), cutoff)).fetchone()
    return max(0.0, float((row or [0])[0] or 0))


def _process_row(d, row, allow_alert):
    eid, ts, token, symbol, action, usd, pool, protocol, txh, block = row
    action = (action or '').upper()
    token = (token or '').lower()
    pool = (pool or '').lower()
    usd = float(usd or 0)
    if not token or not pool or action not in ('ADD', 'REMOVE'):
        return eid

    cur = d.execute(
        'SELECT observed_add_usd,observed_remove_usd,observed_net_usd '
        'FROM pool_flow_state WHERE pool=? AND token=?',
        (pool, token),
    ).fetchone() or (0, 0, 0)
    add, rem, net = map(float, cur)
    pct = None

    if action == 'ADD':
        add += usd
        net += usd
    else:
        baseline = _rolling_baseline(d, eid, ts, token, pool)
        if baseline >= BASE and usd > 0:
            pct = usd / baseline * 100.0
        rem += usd
        net -= usd

    d.execute('''INSERT OR REPLACE INTO pool_flow_state(
      pool,token,symbol,protocol,observed_add_usd,observed_remove_usd,
      observed_net_usd,last_remove_usd,last_drain_pct,last_event_ts
    ) VALUES(?,?,?,?,?,?,?,?,?,?)''', (
        pool, token, symbol, protocol, add, rem, net,
        usd if action == 'REMOVE' else 0, pct, int(ts or time.time()),
    ))

    level = classify(usd, pct) if action == 'REMOVE' and allow_alert else None
    if level:
        key = f'{token}:{pool}'
        prior = d.execute('SELECT ts,level FROM lp_rug_signals WHERE k=?', (key,)).fetchone()
        now = int(time.time())
        allowed = (
            not prior
            or now - int(prior[0]) >= COOL
            or (level == 'P0' and prior[1] != 'P0')
        )
        if allowed:
            d.execute('INSERT OR REPLACE INTO lp_rug_signals(k,ts,level) VALUES(?,?,?)', (key, now, level))
            d.commit()
            monitor.save_alert(
                level, 'lp-rug', protocol or 'AMM', 'REMOVE', usd,
                symbol or '', token, txh or '', int(block or 0),
                f'pool={pool}; observed_drain_pct={pct}; window_hours={WINDOW//3600}',
            )
            monitor.telegram(alert_text(
                level, symbol, token, pool, usd, pct, protocol or 'AMM',
                monitor.LANGUAGE.lower().startswith('zh'),
            ))
    return eid


def run(stop_event=None):
    d = sqlite3.connect(monitor.DB_PATH, timeout=20)
    d.execute('PRAGMA journal_mode=WAL')
    ensure(d)

    # Upgrade safety: build state from retained historical events, but never
    # replay historical withdrawals into Telegram after an upgrade.
    init = d.execute("SELECT v FROM kv WHERE k='lp_rug_initialized'").fetchone()
    if not init:
        last = 0
        while True:
            try:
                rows = d.execute(
                    "SELECT id,ts,token,symbol,action,COALESCE(usd,0),pool,protocol,tx_hash,block_number "
                    "FROM token_events WHERE id>? AND event_type='liquidity' ORDER BY id LIMIT 1000",
                    (last,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                break
            for row in rows:
                last = _process_row(d, row, allow_alert=False)
        _kv(d, 'lp_rug_last_event_id', last)
        _kv(d, 'lp_rug_initialized', 1)
        d.commit()
        log.info('LP Rug baseline initialized through token_event id=%s; historical alerts suppressed', last)
    else:
        row = d.execute("SELECT v FROM kv WHERE k='lp_rug_last_event_id'").fetchone()
        last = int(row[0]) if row else 0

    while stop_event is None or not stop_event.is_set():
        try:
            _kv(d, 'lp_rug_heartbeat', int(time.time()))
            d.commit()
            try:
                rows = d.execute(
                    "SELECT id,ts,token,symbol,action,COALESCE(usd,0),pool,protocol,tx_hash,block_number "
                    "FROM token_events WHERE id>? AND event_type='liquidity' ORDER BY id LIMIT 200",
                    (last,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                if stop_event:
                    stop_event.wait(0.7)
                else:
                    time.sleep(0.7)
                continue

            for row in rows:
                last = _process_row(d, row, allow_alert=True)
                _kv(d, 'lp_rug_last_event_id', last)
                _kv(d, 'lp_rug_heartbeat', int(time.time()))
                d.commit()
        except Exception:
            log.exception('LP rug worker error')
            if stop_event:
                stop_event.wait(1)
            else:
                time.sleep(1)

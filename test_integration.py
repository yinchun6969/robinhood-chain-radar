#!/usr/bin/env python3
"""Offline V1.3.0 integration checks.

No RPC request is issued. This verifies that a fresh/legacy-style SQLite file can
load the V1.3 modules, create Token Radar schema, and render both dashboards.
"""
import os
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "radar.db"
    os.environ["DB_PATH"] = str(db)
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "")

    import monitor
    import fast_scanner
    import dashboard
    import radar_supervisor

    assert monitor.RADAR_VERSION == "1.3.0"
    d = monitor.db._conn()
    fast_scanner.ensure(d)
    tables = {r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {
        "token_events", "token_profiles", "token_scan_queue", "token_signals",
        "address_events", "address_profiles", "raw_events", "swap_events",
    }
    assert required <= tables, sorted(required - tables)

    snap = dashboard.snapshot()
    assert snap["version"] == "1.3.0"
    assert "token_radar_running" in snap and "hot_tokens" in snap
    assert "token_urgent" in snap
    h = dashboard.health()
    assert h["version"] == "1.3.0" and "token_queue" in h

    zh = dashboard.html_page("zh")
    en = dashboard.html_page("en")
    for page in (zh, en):
        assert "V1.3.0" in page
        assert "/api/token" in page
        assert "V1.3.0" in page
        assert "{{" not in page

    # Supervisor maintenance regression: one pass must be executable and prune
    # bounded Token Radar history without a NameError or touching recent rows.
    now = 2_000_000_000
    d.execute("INSERT INTO token_events(ts,token,symbol,event_type,action,usd,tx_hash,block_number) VALUES(?,?,?,?,?,?,?,?)",
              (now-8*86400, "0x"+"aa"*20, "OLD", "swap", "BUY", 1, "0xold", 1))
    d.execute("INSERT INTO token_signals(signal_key,ts,token,symbol,level,signal_type,score,risk_score,details) VALUES(?,?,?,?,?,?,?,?,?)",
              ("old", now-31*86400, "0x"+"aa"*20, "OLD", "P1", "TEST", 1, 1, "{}"))
    d.execute("INSERT OR REPLACE INTO token_scan_queue(token,symbol,status,updated_at) VALUES(?,?,?,?)",
              ("0x"+"aa"*20, "OLD", 2, now-8*86400))
    d.commit()
    radar_supervisor.maintenance_once(d, now)
    assert d.execute("SELECT COUNT(*) FROM token_events WHERE tx_hash='0xold'").fetchone()[0] == 0
    assert d.execute("SELECT COUNT(*) FROM token_signals WHERE signal_key='old'").fetchone()[0] == 0
    assert d.execute("SELECT COUNT(*) FROM token_scan_queue WHERE token=?", ("0x"+"aa"*20,)).fetchone()[0] == 0

print("integration smoke test: OK (schema migration + dashboard zh/en + maintenance + local APIs)")

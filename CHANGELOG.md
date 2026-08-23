# Changelog

## 1.3.1

- Added `doctor.py` one-command runtime diagnostics.
- Added primary + backup RPC automatic failover through a localhost JSON-RPC proxy.
- Added primary RPC failback after a configurable recovery interval.
- Redacted RPC URL paths, query strings and userinfo from health/log labels.
- Added LP Rug Radar with P0/P1 large-liquidity-removal alerts.
- Added rolling observed-flow baseline for LP drain ratios; percentages are explicitly not exact TVL.
- Added upgrade-safe historical LP baseline seeding without replaying old Telegram alerts.
- Added Supervisor-managed LP Rug worker and heartbeat.
- Fixed supervisor self-exec so RPC failover remains active after scanner/RSS-triggered restarts.
- Updated Android / Termux and Ubuntu install + upgrade paths to run through `launcher.py`.
- Added `test_v131.py` offline regressions for RPC failover, secret-safe endpoint labels and LP-risk semantics.
- Added bilingual V1.3.1 documentation and configuration examples.

## 1.3.0

- Added Token Early-Capital Radar.
- Added token-level BUY/SELL, LP and bridge event tracking.
- Added capital, risk and signal scoring.
- Added Bridge → BUY → LP correlation.
- Added Token Radar background worker and queue.
- Added Token Radar Telegram P0/P1 alerts.
- Rebuilt bilingual Dashboard with Token Radar as the default view.
- Added `/api/token` local API.
- Fixed Android/Ubuntu installers to include all intelligence modules.
- Added V1.3 offline static tests and configuration.
- Added priority Token Radar deep-analysis queue.
- Track both sides of non-base token/token pools.
- Added LP-outflow and holder-concentration warning tags.
- Added real P0/P1 signal cooldown with immediate P1 → P0 escalation.
- Added local `/api/health`.
- Fixed supervisor maintenance cleanup, custom `DB_PATH`, and V4 fee formatting.

## 1.2.5

- Token CA, holders, LP flow and heuristic contract-risk enrichment.
- Mobile supervisor / Android keepalive improvements.

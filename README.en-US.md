# Robinhood Chain Radar V1.3.1

> **Unofficial community project:** independent and not affiliated with, endorsed by, or sponsored by Robinhood. See [NOTICE.md](NOTICE.md).

![Robinhood Chain Radar](assets/hero.webp)

A real-time capital-flow and token-intelligence radar for Robinhood Chain mainnet (Chain ID `4663`), supporting Android / Termux and Ubuntu.

V1.3.1 keeps the V1.3 Token Early-Capital Radar and focuses on **runtime reliability and LP-withdrawal risk monitoring**.

## New in V1.3.1

- **One-command Doctor:** checks Python, Chain 4663 RPCs, SQLite, scanner heartbeats, Dashboard, RPC Proxy, Telegram configuration and Blockscout reachability.
- **Multi-RPC automatic failover:** switches from `RH_RPC_URL` to configured `RH_RPC_URLS` backups and periodically retries the primary according to `RPC_FAILBACK_SEC`.
- **Secret-safe endpoint labels:** health output logs protocol + host only, not URL paths, query strings or userinfo that may contain provider API keys.
- **Local failover proxy:** binds to `127.0.0.1:18766` by default so existing scanners gain failover without a large core rewrite.
- **LP Rug Radar:** emits P0 / P1 signals for large liquidity removals.
- **Rolling observed-flow baseline:** percentage alerts use the previous 24h of Radar-observed large LP net flow instead of an ever-growing lifetime counter.
- **No historical alert replay on upgrade:** retained V1.3.0 events seed the baseline but do not resend old withdrawals to Telegram.
- **Supervisor-managed LP Rug Worker:** self-restarts continue through `launcher.py`, preserving the RPC failover layer.

All V1.3.0 features remain: Bridge → BUY → LP correlation, Token CA, holder count, Top1/Top10, 24h BUY/SELL/LP flow, wallet intelligence, heuristic contract-risk analysis, Token P0/P1/P2 signals, bilingual Telegram and `/zh` / `/en` Dashboard views.

## Android / Termux

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

Existing V1.3.0 users can upgrade with:

```bash
cd ~/robinhood-chain-radar
bash upgrade-termux.sh
```

Runtime commands:

```bash
cd ~/robinhood-radar
bash start-termux.sh
bash status-termux.sh
.venv/bin/python doctor.py
```

Dashboard: `http://127.0.0.1:8787/en`

RPC failover health: `http://127.0.0.1:18766/health`

## Ubuntu

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

Upgrade an existing install:

```bash
cd robinhood-chain-radar
git pull
sudo bash scripts/ubuntu/update.sh
```

The systemd service starts `launcher.py`, which creates the localhost failover proxy before starting the supervisor.

## RPC failover settings

```env
RH_RPC_URL=https://primary-rpc.example
RH_RPC_URLS=https://backup-1.example,https://backup-2.example
RPC_FAILBACK_SEC=300
RPC_PROXY_PORT=18766
```

Radar still works with a single RPC, but Doctor reports an `RPC redundancy` warning.

## LP Rug Radar settings

```env
LP_RUG_MIN_REMOVE_USD=250000
LP_RUG_ABSOLUTE_USD=1000000
LP_RUG_P0_DRAIN_PCT=50
LP_RUG_P1_DRAIN_PCT=30
LP_RUG_BASELINE_MIN_USD=500000
LP_RUG_WINDOW_HOURS=24
LP_RUG_COOLDOWN_MIN=15
```

Default semantics:

- P0: one removal ≥ `$1M`, or observed-flow drain ratio ≥ `50%`.
- P1: one removal ≥ `$500K`, or observed-flow drain ratio ≥ `30%`.
- Removals below `$250K` do not enter the LP Rug signal path.

**The drain ratio is not exact TVL loss.** It is derived only from large LP Add/Remove events observed by Radar inside the configured window. V4 USD values remain principal estimates.

## Doctor

```bash
.venv/bin/python doctor.py
```

Machine-readable output:

```bash
.venv/bin/python doctor.py --json
```

Doctor returns `HEALTHY`, `WARN` or `FAIL`. A warning does not necessarily mean the service is down; a single configured RPC, a stopped local Dashboard or missing Telegram credentials can legitimately produce warnings.

## Risk boundary

P0 / P1 / P2 are engineering observation priorities, not investment recommendations. Contract-risk output is heuristic and is not a complete audit or a real buy/sell honeypot simulation. The project does not need private keys, seed phrases or transaction signing.

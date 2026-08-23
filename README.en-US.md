# Robinhood Chain Radar V1.3.0

> **Unofficial community project:** independent and not affiliated with, endorsed by, or sponsored by Robinhood. See [NOTICE.md](NOTICE.md). — English

![V1.3.0](assets/release-card.webp)

A real-time capital-flow radar for Robinhood Chain mainnet (Chain ID `4663`).

V1.3.0 upgrades isolated $1M alerts into a **Token Early-Capital Radar** that correlates bridge inflows, large buys/sells, LP deployment/removal, wallet intelligence, holder concentration and contract-permission risk.

## New in V1.3.0

- **Token capital profiles:** 24h large buys, sells, net buys, LP adds/removes/net flow.
- **Swap direction:** target-token `BUY / SELL` instead of a generic `SWAP` label.
- **Bridge → BUY → LP correlation:** increases priority when the same wallet completes a capital-deployment sequence inside the configured window.
- **Three scores:** capital score, risk score and final signal score.
- **P0 / P1 / P2:** monitoring priorities only, not trading recommendations.
- **Holder concentration:** holder count, Top1 and Top10, excluding the active pool, V4 PoolManager and zero/dead addresses.
- **Contract permission heuristics:** source verification, owner, proxy, mint, blacklist, pause, tax, trading switch, limits and upgrade interfaces.
- **Dedicated Token Worker:** expensive holder/contract analysis is decoupled from realtime event workers.
- **V1.3 Dashboard:** Token Radar default tab, `/api/token`, bilingual `/zh` and `/en`.

## Android / Termux

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

## Ubuntu

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

## V1.3 settings

```env
TOKEN_RADAR_MIN_EVENT_USD=100000
TOKEN_SIGNAL_MIN_SCORE=55
TOKEN_CORRELATION_WINDOW_MIN=180
TOKEN_DEEP_SCAN_TTL_SEC=600
TOKEN_SIGNAL_COOLDOWN_MIN=30
```

## Risk boundary

The risk score is heuristic. It does not prove a token is safe or sellable. V1.3.0 does not execute a real honeypot buy/sell simulation and never needs private keys or transaction signing.

## Local health endpoint

`http://127.0.0.1:8787/api/health` returns scanner, Token Radar, supervisor, block-lag and queue health without exposing the Dashboard publicly.

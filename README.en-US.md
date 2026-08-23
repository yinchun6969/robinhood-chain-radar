# Robinhood Chain Radar

[中文](README.zh-CN.md) | [English](README.en-US.md)

A real-time capital-flow radar for Robinhood Chain mainnet (Chain ID `4663`).

It watches large bridge inflows, Uniswap V2/V3/V4 liquidity events and large swaps, then delivers intelligence through **Telegram + a local Web Dashboard**.

> Current public version: **V1.2.5**

## Features

- Real-time Robinhood Chain block / event-log scanning
- Uniswap V2/V3/V4 add/remove liquidity monitoring
- V4 `ModifyLiquidity` LP principal estimation
- Adaptive V2/V3/V4 large-swap filtering
- Canonical ETH / ERC20 bridge inflow monitoring
- Address intelligence and `Bridge → LP` P0 capital-deployment signals
- **Chinese / English Telegram alerts** (`LANGUAGE=zh_CN` or `en_US`)
- **Chinese / English Dashboard** at `/zh` and `/en`
- Token CA, holder count, Top1 and Top10 concentration
- 24h large-LP add/remove/net-flow statistics
- Heuristic token-contract source/permission risk scan
- Android Supervisor / Wake Lock / Termux:Boot
- Ubuntu systemd service for 24/7 operation

## Quick Start

### Android / Termux

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

Details: [docs/en-US/ANDROID.md](docs/en-US/ANDROID.md)

### Ubuntu 22.04 / 24.04

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

Details: [docs/en-US/UBUNTU.md](docs/en-US/UBUNTU.md)

## Configuration

```env
LANGUAGE=en_US
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ALERT_USD=1000000
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8787
```

For Chinese Telegram alerts:

```env
LANGUAGE=zh_CN
```

Dashboard:

- Chinese: `http://127.0.0.1:8787/zh`
- English: `http://127.0.0.1:8787/en`

## Security Boundary

This is a read-only monitoring tool. It does not need wallet private keys or seed phrases and does not submit transactions. Token-risk output is heuristic and is not a full security audit or honeypot buy/sell simulation.

See [SECURITY.md](SECURITY.md) and [DISCLAIMER.md](DISCLAIMER.md).

## License

MIT

# Robinhood Chain Radar

**Robinhood Chain 实时资金雷达 / Real-time Capital Flow Intelligence**

[简体中文](README.zh-CN.md) · [English](README.en-US.md)

> Public version / 公开版: **V1.2.5**  
> Robinhood Chain Mainnet: **Chain ID 4663**

Robinhood Chain Radar is a read-only monitoring stack for tracking large capital movements on Robinhood Chain. It focuses on large bridge inflows, Uniswap V2/V3/V4 liquidity and swaps, hot-wallet behavior, token intelligence, and fast Telegram alerts.

Robinhood Chain Radar 是一套只读的 Robinhood Chain 链上资金监控系统，重点监控百万美元级跨链资金、Uniswap V2/V3/V4 流动性、大额 Swap、热点地址以及 Token CA / 持有人 / LP / 合约风险，并通过 Telegram 与本地 Dashboard 实时展示。

## Highlights / 核心功能

- Large bridge inflow alerts / 大额跨链资金告警
- Uniswap V2/V3/V4 liquidity monitoring / V2/V3/V4 流动性监控
- Large swap adaptive filtering / 大额 Swap 自适应过滤
- Address intelligence and Bridge → LP signals / 地址画像与跨链→加池强信号
- Token CA, holders, LP and heuristic contract-risk checks / CA、持有人、LP 与启发式合约风险检查
- Chinese / English Telegram alerts / 中英文 Telegram 推送
- Chinese / English local Dashboard / 中英文本地面板
- Android Termux and Ubuntu deployment / Android Termux 与 Ubuntu 双方案

## Quick Start / 快速开始

### Android / Termux

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

### Ubuntu 22.04 / 24.04

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

## Language / 语言

```env
# 中文 Telegram / 默认中文
LANGUAGE=zh_CN

# English Telegram
# LANGUAGE=en_US
```

Dashboard routes / 面板地址：

- 中文：`http://127.0.0.1:8787/zh`
- English: `http://127.0.0.1:8787/en`

## Documentation / 文档

| 中文 | English |
|---|---|
| [Android / Termux](docs/zh-CN/ANDROID.md) | [Android / Termux](docs/en-US/ANDROID.md) |
| [Ubuntu](docs/zh-CN/UBUNTU.md) | [Ubuntu](docs/en-US/UBUNTU.md) |
| [架构说明](docs/zh-CN/ARCHITECTURE.md) | [Architecture](docs/en-US/ARCHITECTURE.md) |

## Security / 安全

No wallet private key or seed phrase is required. The project does not submit transactions. Keep `.env` private because it can contain your Telegram Bot Token and Chat ID.

本项目不需要钱包私钥或助记词，不执行链上交易。`.env` 可能包含 Telegram Bot Token 与 Chat ID，请勿上传到 GitHub。

Token-risk results are heuristic signals rather than a full smart-contract audit or guaranteed honeypot detection.

Token 合约风险结果属于启发式风险提示，不等同于完整智能合约审计，也不保证识别所有 Honeypot 风险。

See [SECURITY.md](SECURITY.md) and [DISCLAIMER.md](DISCLAIMER.md).

## License

MIT

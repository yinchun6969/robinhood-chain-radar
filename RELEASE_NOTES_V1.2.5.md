# Robinhood Chain Radar V1.2.5 — Public Release

[中文](#中文) | [English](#english)

## 中文

Robinhood Chain Radar V1.2.5 现已正式公开。

这是一个面向 Robinhood Chain Mainnet（Chain ID `4663`）的只读链上资金监控项目，重点追踪：

- 百万美元级跨链资金流入
- Uniswap V2 / V3 / V4 大额加池与撤池
- 大额 Swap 自适应过滤
- Bridge → LP 资金部署强信号
- Token CA、持有人集中度、LP 情况与启发式合约风险
- Telegram 中文 / 英文告警
- 本地中英文 Dashboard
- Android / Termux 与 Ubuntu 双部署方案

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

项目不需要私钥或助记词，也不会执行交易。风险判断属于启发式链上分析，并非完整合约审计。

欢迎提交 Issue / Pull Request。

---

## English

Robinhood Chain Radar V1.2.5 is now publicly available.

It is a read-only capital-flow monitoring stack for Robinhood Chain Mainnet (Chain ID `4663`) focused on:

- Million-dollar bridge inflows
- Large Uniswap V2 / V3 / V4 liquidity additions and removals
- Adaptive large-swap filtering
- Bridge → LP capital-deployment signals
- Token CA, holder concentration, LP state and heuristic contract-risk checks
- Chinese / English Telegram alerts
- Local bilingual Dashboard
- Android / Termux and Ubuntu deployment

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

No private key or seed phrase is required and the project does not submit transactions. Risk output is heuristic on-chain intelligence, not a complete smart-contract audit.

Issues and pull requests are welcome.

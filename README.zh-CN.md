# Robinhood Chain Radar

[中文](README.zh-CN.md) | [English](README.en-US.md)

Robinhood Chain 主网（Chain ID `4663`）实时资金雷达。

监控大额跨链、Uniswap V2/V3/V4 流动性与大额 Swap，通过 **Telegram + 本地 Web Dashboard** 输出资金情报。

> 当前公开版：**V1.2.5**

## 主要功能

- Robinhood Chain 实时区块 / Event Logs 扫描
- Uniswap V2/V3/V4 Add / Remove Liquidity
- V4 `ModifyLiquidity` LP 本金估值
- V2/V3/V4 大额 Swap 自适应过滤
- Canonical ETH / ERC20 跨链资金监控
- 地址画像与 `Bridge → LP` P0 强信号
- **中英文 Telegram 告警**（`LANGUAGE=zh_CN` / `en_US`）
- **中英文 Dashboard**：`/zh` 与 `/en`
- Token CA / holder count / Top1 / Top10
- 24h 大额 LP 加池、撤池与净变化
- Token 合约权限/源码启发式风险扫描
- Android Supervisor / Wake Lock / Termux:Boot
- Ubuntu systemd 24/7 服务

## 快速部署

### Android / Termux

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

详细说明：[docs/zh-CN/ANDROID.md](docs/zh-CN/ANDROID.md)

### Ubuntu 22.04 / 24.04

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

详细说明：[docs/zh-CN/UBUNTU.md](docs/zh-CN/UBUNTU.md)

## 配置

```env
LANGUAGE=zh_CN
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ALERT_USD=1000000
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8787
```

英文 Telegram：

```env
LANGUAGE=en_US
```

Dashboard：

- 中文：`http://127.0.0.1:8787/zh`
- English: `http://127.0.0.1:8787/en`

## 安全边界

本项目为只读监控工具，不需要私钥、助记词，也不执行交易。Token 风险扫描属于启发式检查，不等同于完整安全审计或 Honeypot 买卖模拟。

详见 [SECURITY.md](SECURITY.md) 与 [DISCLAIMER.md](DISCLAIMER.md)。

## License

MIT

# Robinhood Chain Radar V1.3.1

> **非官方社区项目：** 本项目与 Robinhood 不存在隶属、授权、赞助或官方背书关系。详见 [NOTICE.md](NOTICE.md)。

![Robinhood Chain Radar](assets/hero.webp)

Robinhood Chain 主网（Chain ID `4663`）实时资金与 Token 情报雷达，支持 Android / Termux 与 Ubuntu。

V1.3.1 在 V1.3.0 Token Early-Capital Radar 基础上重点强化 **可靠性和撤池风险监控**。

## V1.3.1 新增

- **一键 Doctor**：检查 Python、Chain 4663 RPC、备用 RPC、SQLite、Scanner 心跳、Dashboard、RPC Proxy、Telegram 配置与 Blockscout 可达性。
- **多 RPC 自动容灾**：主 RPC 失败后自动切换到 `RH_RPC_URLS` 备用端点，并按 `RPC_FAILBACK_SEC` 尝试恢复主 RPC。
- **隐私安全日志**：RPC 健康信息只展示协议 + Host，不输出 URL Path、Query、Userinfo，降低第三方 RPC API Key 泄漏风险。
- **本地 Failover Proxy**：默认仅监听 `127.0.0.1:18766`，现有 Scanner 无需大规模重构即可获得容灾能力。
- **LP Rug Radar**：对大额 `REMOVE` 事件发出 P0 / P1 撤池风险提示。
- **滚动观察基线**：撤池比例使用最近 24h Radar 已观察到的大额 LP 净流作为基线，不使用永久累计值。
- **升级不补发旧警报**：V1.3.0 数据首次迁移只建立 LP 基线，不把历史撤池重新推送到 Telegram。
- **Supervisor 正式托管 LP Rug Worker**，并保证自我重启后仍从 `launcher.py` 恢复 RPC 容灾层。

V1.3.0 的 Token Radar 功能全部保留：Bridge → BUY → LP、Token CA、持有人数量、Top1/Top10、24h BUY/SELL/LP、地址画像、合约权限风险、P0/P1/P2 Token 信号、中英文 Telegram 与 Dashboard。

## Android / Termux 安装

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

已有 V1.3.0 用户升级：

```bash
cd ~/robinhood-chain-radar
bash upgrade-termux.sh
```

安装目录默认是 `~/robinhood-radar`。

```bash
cd ~/robinhood-radar
bash start-termux.sh
bash status-termux.sh
.venv/bin/python doctor.py
```

中文 Dashboard：`http://127.0.0.1:8787/zh`

RPC 容灾状态：`http://127.0.0.1:18766/health`

## Ubuntu 安装

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

已有安装升级：

```bash
cd robinhood-chain-radar
git pull
sudo bash scripts/ubuntu/update.sh
```

服务由 systemd 运行 `launcher.py`，由 Launcher 建立本地 RPC Failover Proxy 后再启动 Supervisor。

## RPC 自动容灾配置

```env
RH_RPC_URL=https://primary-rpc.example
RH_RPC_URLS=https://backup-1.example,https://backup-2.example
RPC_FAILBACK_SEC=300
RPC_PROXY_PORT=18766
```

如果没有备用 RPC，Radar 仍可运行，但 Doctor 会显示 `RPC redundancy` 警告。

## LP Rug Radar 配置

```env
LP_RUG_MIN_REMOVE_USD=250000
LP_RUG_ABSOLUTE_USD=1000000
LP_RUG_P0_DRAIN_PCT=50
LP_RUG_P1_DRAIN_PCT=30
LP_RUG_BASELINE_MIN_USD=500000
LP_RUG_WINDOW_HOURS=24
LP_RUG_COOLDOWN_MIN=15
```

默认规则：

- P0：单笔撤池 ≥ `$1M`，或撤出比例 ≥ `50%`。
- P1：单笔撤池 ≥ `$500K`，或撤出比例 ≥ `30%`。
- 低于 `$250K`` 的撤池不进入 LP Rug 信号。

**重要：撤出比例不是精确 TVL 变化。** 它只基于 Radar 在配置窗口内已记录的大额 LP Add/Remove 净流。V4 的美元金额仍然是本金估算。

## Doctor

```bash
.venv/bin/python doctor.py
```

机器可读 JSON：

```bash
.venv/bin/python doctor.py --json
```

Doctor 返回 `HEALTHY / WARN / FAIL`。`WARN` 不一定意味着服务停止，例如仅配置一个 RPC、Dashboard 尚未启动或 Telegram 未配置都会产生警告。

## 风险边界

P0 / P1 / P2 是工程监控优先级，不是投资建议。合约风险扫描是启发式权限/源码检查，不是完整安全审计，也不执行真实买卖 Honeypot 模拟。本项目不需要私钥、助记词或交易签名。

详细安全说明见 [SECURITY.md](SECURITY.md)。

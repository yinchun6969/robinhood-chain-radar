# Robinhood Chain Radar V1.3.1

## 中文

V1.3.1 是 V1.3 Token Early-Capital Radar 的可靠性版本，重点解决长期运行和 LP 大规模撤出风险监控。

### 新增

- `doctor.py` 一键健康检查。
- `RH_RPC_URLS` 多 RPC 自动容灾。
- 主 RPC 恢复后的自动 Failback。
- 本地 `127.0.0.1:18766` JSON-RPC Failover Proxy。
- RPC URL Path / Query / Userinfo 脱敏显示。
- LP Rug Radar：P0 / P1 大额撤池警报。
- 最近 24h Radar 已观察大额 LP 净流滚动基线。
- 升级时历史 LP 事件只建立基线，不补发旧 Telegram 警报。
- Android / Termux 与 Ubuntu 安装、升级路径统一使用 `launcher.py`。

### 默认 LP 风险规则

- P0：单笔撤池 ≥ `$1M`，或观察基线撤出比例 ≥ `50%`。
- P1：单笔撤池 ≥ `$500K`，或观察基线撤出比例 ≥ `30%`。
- 最低分析金额：`$250K`。

> 撤出比例仅基于 Radar 已观察到的大额 LP Add/Remove 净流，不代表精确池 TVL。V4 金额仍为本金估算。

### 升级

Android / Termux：

```bash
cd ~/robinhood-chain-radar
git pull
bash upgrade-termux.sh
```

Ubuntu：

```bash
cd robinhood-chain-radar
git pull
sudo bash scripts/ubuntu/update.sh
```

诊断：

```bash
.venv/bin/python doctor.py
```

---

## English

V1.3.1 is the reliability-focused follow-up to the V1.3 Token Early-Capital Radar. It improves long-running RPC resilience and adds large LP-withdrawal risk monitoring.

### Added

- One-command `doctor.py` diagnostics.
- Multi-RPC automatic failover with `RH_RPC_URLS`.
- Configurable failback to the recovered primary RPC.
- Localhost JSON-RPC failover proxy on `127.0.0.1:18766`.
- Secret-safe RPC labels that omit URL paths, query strings and userinfo.
- LP Rug Radar with P0 / P1 large-withdrawal signals.
- Rolling 24h Radar-observed large-LP net-flow baseline.
- Upgrade-safe historical baseline seeding without replaying old Telegram alerts.
- Android / Termux and Ubuntu startup paths now use `launcher.py`.

### Default LP-risk semantics

- P0: one removal ≥ `$1M`, or observed-flow drain ratio ≥ `50%`.
- P1: one removal ≥ `$500K`, or observed-flow drain ratio ≥ `30%`.
- Minimum analyzed removal: `$250K`.

> The drain ratio is based only on large LP Add/Remove events observed by Radar and is not exact pool TVL. V4 USD values remain principal estimates.

### Upgrade

Android / Termux:

```bash
cd ~/robinhood-chain-radar
git pull
bash upgrade-termux.sh
```

Ubuntu:

```bash
cd robinhood-chain-radar
git pull
sudo bash scripts/ubuntu/update.sh
```

Diagnostics:

```bash
.venv/bin/python doctor.py
```

P0 / P1 / P2 remain engineering observation priorities and are not investment recommendations.

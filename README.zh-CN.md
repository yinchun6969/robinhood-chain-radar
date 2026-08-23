# Robinhood Chain Radar V1.3.0

> **非官方社区项目：** 本项目与 Robinhood 不存在隶属、授权、赞助或官方背书关系。详见 [NOTICE.md](NOTICE.md)。 — 中文

![V1.3.0](assets/release-card.webp)

Robinhood Chain 主网（Chain ID `4663`）实时资金雷达。

V1.3.0 的重点从“单笔百万美元警报”升级为 **Token 早期资金雷达**：把一个代币相关的跨链、买入、卖出、加池、撤池、热点地址、持有人集中度和合约权限风险放到同一条资金时间线上。

## V1.3.0 新功能

- **Token 资金画像**：24h 大额买入、卖出、净买入、LP 加池、撤池、净变化。
- **Swap 方向识别**：不再只记录 `SWAP`，会区分目标代币 `BUY / SELL`。
- **Bridge → BUY → LP**：同一资金地址在设定窗口内完成跨链、买入和加池时提高信号权重。
- **三套评分**：资金分、风险分、最终信号分。
- **P0 / P1 / P2**：作为监控优先级，不代表买入建议。
- **持有人集中度**：持有人数量、Top1、Top10，并排除当前池、V4 PoolManager、零地址和销毁地址。
- **合约权限扫描**：源码验证、Owner、Proxy、增发、黑名单、暂停、税费、交易开关、限额、升级接口等启发式检查。
- **独立 Token 后台 Worker**：重型持有人/合约分析从实时事件处理线程拆出，避免拖慢扫链。
- **优先级分析队列**：百万美元、新池、撤池等事件优先执行深度分析，避免普通 Token backlog 挡住关键告警。
- **双 Token 池不漏侧**：非 WETH/USDG 的 Token/Token 池会分别为两侧建立画像。
- **LP 流出与集中度标签**：LP 撤出比例、Top1/Top10 高集中、低持有人数会直接出现在 Token 标签中。
- **V1.3 Dashboard**：新增 Token Radar 首页标签、Token 详情 API `/api/token`、中英文 `/zh` / `/en`。

## 安装：Android / Termux

```bash
pkg update
pkg install -y git
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
bash scripts/android/install-termux.sh
```

安装后：

```bash
cd ~/robinhood-radar
bash start-termux.sh
bash status-termux.sh
```

中文 Dashboard：`http://127.0.0.1:8787/zh`

健康检查：`http://127.0.0.1:8787/api/health`

## 安装：Ubuntu

```bash
git clone https://github.com/yinchun6969/robinhood-chain-radar.git
cd robinhood-chain-radar
sudo bash scripts/ubuntu/install.sh
```

服务管理：

```bash
sudo systemctl status robinhood-chain-radar
sudo systemctl restart robinhood-chain-radar
sudo journalctl -u robinhood-chain-radar -f
```

## V1.3 参数

```env
TOKEN_RADAR_MIN_EVENT_USD=100000
TOKEN_SIGNAL_MIN_SCORE=55
TOKEN_CORRELATION_WINDOW_MIN=180
TOKEN_DEEP_SCAN_TTL_SEC=600
TOKEN_SIGNAL_COOLDOWN_MIN=30
```

- `TOKEN_RADAR_MIN_EVENT_USD`：进入 Token Radar 的单笔事件最低美元值。
- `TOKEN_SIGNAL_MIN_SCORE`：允许发送 P0/P1 Token Telegram 观察信号的最低分。
- `TOKEN_CORRELATION_WINDOW_MIN`：Bridge → BUY → LP 最大关联时间窗口。
- `TOKEN_DEEP_SCAN_TTL_SEC`：持有人/合约深度扫描缓存时间，降低 Explorer 压力。
- `TOKEN_SIGNAL_COOLDOWN_MIN`：同类 Token P0/P1 告警冷却时间，避免时间桶边界重复推送；P1 → P0 升级仍可立即提醒。

## 风险边界

风险分是**启发式评分**，不能证明代币安全，也不能证明可正常卖出。当前版本不执行真实买卖 honeypot 模拟，不读取私钥，不签名交易。

详细安全说明见 [SECURITY.md](SECURITY.md)。

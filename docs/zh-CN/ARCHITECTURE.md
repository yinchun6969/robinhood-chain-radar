# V1.3.0 架构说明

![V1.3.0 Architecture](../../assets/architecture.webp)

V1.3.0 在 V1.2.5 的实时扫描管线之上增加了 **Token 早期资金雷达**。原则是：实时扫描线程只做轻量记录，持有人/源码/权限等较慢分析交给独立后台 Worker，避免 Token 情报拖慢区块同步。

```text
Robinhood Chain RPC
        │
        ├──────────────► Native ETH Scanner ─────► Address Intel
        │
        ▼
   Fast Scanner
        │
        ├── Bridge / LP / Pool Metadata ─► Priority Event Workers
        │                                      │
        │                                      ├──► Address Intel
        │                                      └──► Token Events ─┐
        │                                                         │
        └── All Swaps ─► Adaptive Swap Filters ─► BUY / SELL ─────┤
                                                                  ▼
                                                        Token Scan Queue
                                                                  │
                                                                  ▼
                                                           Token Worker
                                                                  │
                     ┌────────────────────────────────────────────┼───────────────┐
                     ▼                                            ▼               ▼
               Holder Stats                                Contract Risk   Capital Timeline
               Top1 / Top10                               owner/proxy/...  Bridge→BUY→LP
                     └──────────────────────────────┬──────────────┘               │
                                                    ▼                              │
                                              Token Profile ◄──────────────────────┘
                                                    │
                                      Capital / Risk / Signal Score
                                                    │
                                  ┌─────────────────┴─────────────────┐
                                  ▼                                   ▼
                         Dashboard /zh /en                    Telegram P0/P1
```

## 三条主要数据通道

### 1. 优先事件通道

- Canonical Bridge：P130，不因普通积压过期。
- LP Add/Remove：P120，优先处理大额流动性。
- Pool Metadata / Initialize：P90，为 V2/V3/V4 池解析提供元数据。

### 2. Swap 通道

所有 Swap 先进入独立队列，再由 1–3 个自适应过滤 Worker 处理：

- 小额事件直接丢弃；
- 无可靠锚定价格的事件进入丢弃/抽样检查；
- 达到阈值的 Swap 识别目标 Token 和 `BUY / SELL` 方向；
- 同时写入 Address Intel 与 Token Radar。

### 3. Token 深度分析通道

`token_radar.py` 只在实时处理阶段写入紧凑事件并入队。`token_worker.py` 在后台执行：

- Token CA / metadata；
- 持有人数量；
- Top1 / Top10 集中度；
- 源码验证 / owner / proxy / mint / blacklist / pause / tax / trading-control 等启发式检查；
- 24h 大额 BUY / SELL / 净买入；
- 24h LP 加池 / 撤池 / 净变化；
- 活跃地址与高分地址数量；
- 同地址 `Bridge → BUY → LP` 时间关联；
- `Capital Score`、`Risk Score`、`Signal Score`；
- P0/P1 Telegram 观察信号。

## V4 说明

Uniswap V4 `ModifyLiquidity` 不直接提供最终 token0/token1 本金数量。Radar 使用 Pool metadata、tick range、`liquidityDelta` 和 StateView 状态计算 **LP principal estimate**。手续费和 Hook delta 不会作为本金展示。

## 数据存储与保留

SQLite 使用 WAL 模式。V1.3.0 新增：

- `token_events`
- `token_profiles`
- `token_scan_queue`
- `token_signals`

运行维护默认保留约 7 天 Token 事件和 30 天 Token 信号，以限制手机/VPS 长期运行时的数据库增长。Token 评分窗口仍以最近 24 小时为主。

## 安全边界

P0/P1/P2 是监控优先级，不是买卖建议。Risk Score 是静态/权限/持仓集中度启发式结果，不等于完整智能合约审计，也不执行真实买卖 Honeypot 模拟。

## V1.3.0 Token 深度分析队列

事件线程只写 SQLite 并入队；`token_worker.py` 再执行 Explorer/Holder/合约深度分析。队列按事件优先级处理：百万美元、新池、撤池、跨链优先于普通事件。非基础币 Token/Token 池会为两侧分别写入 Token 事件。

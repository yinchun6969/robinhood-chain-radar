# Robinhood Chain Radar V1.3.0

## 中文

V1.3.0 主题：**Token 早期资金雷达**。

主要新增：

1. `token_radar.py`：Token 事件库、资金画像、风险/资金/信号三评分。
2. `token_worker.py`：后台执行持有人和合约深度分析，避免阻塞实时 Worker。
3. Swap 自动识别目标代币 BUY / SELL。
4. Bridge → BUY → LP 资金路径关联。
5. Token P0/P1 Telegram 中文/英文信号。
6. Dashboard V1.3.0：Token Radar 默认页面、风险条、资金净流、持有人集中度、`/api/token`。
7. Android / Ubuntu 安装器补齐 `token_intel.py`、`token_radar.py`、`token_worker.py`，并保留升级时的 `.env` / `radar.db`。
8. 新增 V1.3 配置参数和静态测试。
9. 高优先级 Token 队列：百万美元、新池、撤池优先做深度分析。
10. Token/Token 非基础币池同时追踪两侧，避免漏掉另一侧新币。
11. 新增 LP OUTFLOW、Top1/Top10 集中度、低持有人数风险标签。
12. Telegram 同类信号改为真实冷却时间，避免半小时边界重复推送，同时允许 P1 → P0 即时升级。
13. 新增 `/api/health` 本地健康接口。
14. 修复长期运行维护循环的时间变量问题、自定义 `DB_PATH` 一致性和 V4 fee 百分比格式。

### 兼容性

旧 `radar.db` 可以直接升级。V1.3.0 会自动创建新的 `token_events`、`token_profiles`、`token_scan_queue`、`token_signals` 表，不删除旧表。

## English

V1.3.0 theme: **Token Early-Capital Radar**.

Highlights:

1. Token-level event storage and capital/risk/signal scoring.
2. Dedicated background token-analysis worker.
3. BUY/SELL target-token direction for large swaps.
4. Bridge → BUY → LP capital-deployment correlation.
5. Bilingual P0/P1 Token Radar Telegram alerts.
6. V1.3 Dashboard with Token Radar, holder concentration and `/api/token`.
7. Fixed Android/Ubuntu deployment file lists for the token-intelligence modules.
8. New V1.3 configuration and offline static tests.
9. Priority Token Radar queue for million-dollar/new-pool/LP-removal events.
10. Both sides of non-base token/token pools are tracked.
11. LP-outflow, Top1/Top10 concentration and low-holder warning tags.
12. Real signal cooldowns instead of half-hour buckets, while allowing P1 → P0 escalation.
13. Local `/api/health` endpoint.
14. Long-run maintenance, custom `DB_PATH`, and V4 fee-formatting fixes.

### Upgrade compatibility

Existing `radar.db` databases are migrated in place by creating new V1.3 tables. Existing address/alert/pipeline data is preserved.

## Project status / 项目属性

Independent community open-source project; not affiliated with, endorsed by, or sponsored by Robinhood. / 独立社区开源项目，与 Robinhood 不存在隶属、授权、赞助或官方背书关系。

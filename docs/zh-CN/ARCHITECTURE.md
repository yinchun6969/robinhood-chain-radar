# 架构说明

```text
Robinhood Chain RPC
        │
        ▼
   Fast Scanner
        │
   ┌────┼───────────────┐
   │    │               │
Bridge  LP          Pool Metadata
P130   P120              P90
   │    │               │
   └────┴──────┬────────┘
               ▼
        Address Intelligence
               │
               ├── Telegram 中文警报
               └── 本地 Dashboard

全部 Swap
   │
   ▼
Adaptive Swap Filters (1~3)
   │
   ├── 小额丢弃
   ├── 无锚定价格丢弃 + shadow sampling
   └── ≥$100K confirmed → 地址画像

V4 unresolved poolId
   │
   ▼
Background Resolver
```

V4 `ModifyLiquidity` 的美元数是本金估算，不把手续费或 Hook delta 当成本金。

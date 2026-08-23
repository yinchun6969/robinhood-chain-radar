# Architecture

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
               ├── Telegram alerts (ZH/EN)
               └── Local Dashboard (ZH/EN)

All Swaps → Adaptive Swap Filters (1~3) → large confirmed swaps → address intelligence
V4 unresolved poolId → Background Resolver
```

V4 `ModifyLiquidity` USD value is a principal estimate; fees and Hook deltas are not presented as principal.

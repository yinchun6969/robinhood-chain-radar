# V1.3.0 Architecture

![V1.3.0 Architecture](../../assets/architecture.webp)

V1.3.0 adds the **Token Early-Capital Radar** on top of the V1.2.5 realtime pipeline. The core rule is to keep realtime workers cheap: they persist compact events, while slower holder/source/permission analysis runs in a dedicated background worker.

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

## Main data lanes

### Priority lane

- Canonical Bridge: P130; it is not expired by ordinary realtime backlog cleanup.
- LP Add/Remove: P120 for high-priority liquidity processing.
- Pool Metadata / Initialize: P90 for V2/V3/V4 resolution.

### Swap lane

All swaps enter a separate queue handled by 1–3 adaptive filter workers:

- small events are dropped early;
- unanchored price events are dropped or shadow-sampled;
- qualifying swaps resolve the focus token and `BUY / SELL` direction;
- confirmed events feed both Address Intel and Token Radar.

### Token deep-analysis lane

`token_radar.py` only records compact events and enqueues tokens in the realtime path. `token_worker.py` performs slower analysis in the background:

- token CA / metadata;
- holder count;
- Top1 / Top10 concentration;
- heuristic source / owner / proxy / mint / blacklist / pause / tax / trading-control checks;
- 24h large BUY / SELL / net-buy flow;
- 24h LP add / remove / net flow;
- active and high-score wallet counts;
- same-wallet `Bridge → BUY → LP` correlation;
- Capital, Risk and Signal scores;
- bilingual P0/P1 Telegram observation signals.

## Uniswap V4

`ModifyLiquidity` does not directly expose final token0/token1 principal amounts. Radar derives an **LP principal estimate** from pool metadata, tick range, `liquidityDelta` and StateView state. Fees and Hook deltas are not presented as principal.

## Storage and retention

SQLite runs in WAL mode. V1.3.0 adds:

- `token_events`
- `token_profiles`
- `token_scan_queue`
- `token_signals`

Maintenance keeps roughly 7 days of token events and 30 days of token signals to bound long-running mobile/VPS database growth. Token scoring itself remains primarily a rolling 24h view.

## Safety boundary

P0/P1/P2 are monitoring priorities, not trading recommendations. Risk Score is a static permission/concentration heuristic, not a full smart-contract audit and not a live honeypot buy/sell simulation.

## V1.3.0 Priority Token Queue

Realtime event handlers only persist compact SQLite events and enqueue tokens. `token_worker.py` performs Explorer/holder/contract deep analysis in the background. Million-dollar, new-pool, LP-removal and bridge events receive higher priority. Non-base token/token pools generate a profile event for both sides.

# HyperSmart Known Limitations

- Explorer observer has no enabled unverified network endpoint.
- WebSocket monitor is planned/read-only and bounded.
- Backtests use approximations for fees, spread, slippage and latency.
- Pattern detection is conservative and requires enough evidence.
- Historical PnL is not future PnL.
- Paper trading is not an order and cannot expose capital.
## Current high-priority limitations

- Live scan cannot user-stream thousands of wallets; it must shortlist and rotate.
- 2000 wallets/s target is local-only, not API throughput.
- Local index currently has in-memory fallback; persistent DuckDB/Parquet is future work.
- Simulation is honest and can stay red; no code may force positive PnL.
- Provider integrations beyond official Hyperliquid are disabled by default.

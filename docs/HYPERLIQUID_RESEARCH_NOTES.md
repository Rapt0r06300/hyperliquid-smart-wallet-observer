# Hyperliquid Research Notes

Before Sprint 2 network implementation, re-check the official Hyperliquid
documentation for:

- `/info`;
- `meta`;
- `userFills`;
- `userFillsByTime`;
- `clearinghouseState`;
- `openOrders`;
- `l2Book`;
- WebSocket subscriptions;
- rate limits and user limits;
- testnet faucet and mock USDC rules.

These notes are not a substitute for current official documentation. Network
code must be read-only until the locked testnet sprint.

## Sprint 2 implementation notes

- All network reads go through the centralized `HyperliquidInfoClient`.
- Requests are POST-only to the info endpoint.
- `userFillsByTime` pagination is bounded and stops on empty responses,
  non-progressing timestamps or configured page limits.
- Read-only collection is disabled unless `--network-read` is supplied and
  `HYPERSMART_ENABLE_NETWORK_READS` is enabled for the runtime invocation.
- `userFillsByTime` responses may be limited by Hyperliquid, so backfills must
  treat missing history as incomplete data rather than inventing state.

## Sprint 3 scoring notes

- Scoring reads local SQLite fills only; it does not call Hyperliquid.
- A fill is not automatically a closed trade. Trade-level metrics are only
  computed from locally stored `closed_pnl` values when they exist.
- If closed PnL is absent, the scorer may still report fill counts and data
  quality, but final wallet scores are withheld by default.
- Sharpe, Sortino and Calmar are non-annualized local diagnostics because fill
  spacing may not represent a stable time period.
- Future trade reconstruction must validate entry/exit pairing before using
  more advanced PnL or methodology statistics.

## Sprint 4 paper simulation notes

- Paper simulation does not call Hyperliquid and does not know the real future
  fill price.
- Spread, slippage and latency are configured approximations. Real execution
  could differ materially.
- Paper results should be interpreted as research diagnostics, not as a
  recommendation or a profit forecast.
- Future sprints may compare multiple paper scenarios, but testnet execution
  remains out of scope until explicitly locked and guarded.

## Long-run observer notes

- `/info` remains the only REST path used by the HyperSmart read-only client.
- Explorer observer is an abstraction for public or manually imported events;
  unverified network endpoints are not enabled by default.
- WebSocket monitoring is read-only, bounded and limited for user-specific
  streams.
- Position lifecycle reconstruction must preserve `UNKNOWN` when fields such as
  `dir`, `startPosition`, price or size are ambiguous.
- Backtesting uses local data only and must include pessimistic cost assumptions.

## Copy observer data surfaces

- `clearinghouseState` provides signed position state for snapshot diffs.
- `userFills` and `userFillsByTime` provide fill fields such as `dir`,
  `startPosition` and `closedPnl` for delta classification and outcomes.
- `openOrders` and `frontendOpenOrders` are context only; they do not prove an
  executed position.
- WebSocket shortlist monitoring is read-only, duration-limited and must not
  exceed user-specific subscription limits.
- Explorer data is a public hint unless full addresses and payloads are
  revalidated. Truncated addresses never create candidates.

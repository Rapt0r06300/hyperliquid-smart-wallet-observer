# HyperSmart Magic Bot Research Digest

Date: 2026-05-26

Scope: public research only. HyperSmart implements observation, scoring,
paper mock USDC simulation and local backtesting. It does not implement real
order execution.

## Safety Position

The public "bot magique" narrative is mostly a copy-trading architecture:
find leaders, observe their positions/fills/orders, detect deltas, then mirror
locally or live. HyperSmart only reproduces the safe, measurable part:

- read-only `/info`;
- read-only WebSocket planning/monitoring;
- local paper mock USDC;
- no `/exchange`;
- no signature;
- no private key;
- no mainnet;
- no active testnet executor;
- no promise of profit.

## Sources Reviewed

| Source | Public Finding | HyperSmart Translation |
|---|---|---|
| LearnWithMeAI Claude copy bot article | Three decoupled jobs: daily leaderboard shortlist, 5-minute copy loop, reporting/paper portfolio. | `copy-preflight`, `copy-run --interval 300 --dry-run`, `copy-report`, shortlist JSON, no-trade reports. |
| Hyperliquid official `/info` docs | Public user state/fills/open orders can be queried through `/info` payloads. | `HyperliquidInfoClient` supports `allMids`, `clearinghouseState`, `userFillsByTime`, `userFills`, `openOrders`, `frontendOpenOrders`, `userFees`, `userRateLimit`. |
| Hyperliquid official rate limits | REST has a shared weight limit; some `/info` endpoints have extra weight by returned items. | Conservative caps: page limit 500, max pages/wallet 5, max fills/run 10000, local rate limiter, stopped_reason. |
| Hyperliquid official WebSocket docs | WS is useful for live public/user streams but must be bounded. | Read-only shortlist WS modules, max 10 user-specific users, duration required, dry-run default. |
| Chainstack Hyperliquid copy trading guide | Real-time copy requires order/event sequencing, `orderUpdates`, `userEvents`, dynamic sizing, and state management. | HyperSmart treats open orders as context only and waits for fills/positions before paper simulation. |
| Dwellir gRPC copy bot example | Production-style copy bots stream fills, dedupe fills, use `dir`, use min/max notional, max open positions, slippage tolerance, dry-run first. | HyperSmart uses fill dedupe, `dir` classification, edge degradation, min/max paper notional, and local-only paper. |
| MaxIsOntoSomething Hyperliquid_Copy_Trader | Uses WebSocket monitoring, account-balance-ratio sizing, asset filters, leverage adjustment, simulated mode. | Added `copy_mode/sizing.py`: leader/follower equity ratio, notional cap, min notional, blocked assets, refusal if key data missing. |
| PerpLobster | Web dashboard, event-driven architecture, JSON config, SQLite metrics tracking. | HyperSmart uses local SQLite, read-only dashboard export, JSON/Markdown/CSV reports. |

## Reproducible Architecture

### Job A: Leaderboard / Discovery

Inputs:

- CSV/JSON/TXT imports;
- local fills and scores;
- future explorer/read-only sources;
- full wallet addresses only.

Filters:

- address must be `0x` + 40 hex characters;
- no truncated addresses;
- minimum history days;
- minimum closed PnL points;
- max drawdown;
- PnL concentration;
- one-big-win risk;
- consistency;
- execution quality;
- sample confidence;
- copyability.

Output:

- `data/leaderboard_shortlist.json`;
- `leaderboard_shortlist` DB rows;
- rejected/watch-only statuses with reasons.

### Job B: Copy Loop Dry-Run

Inputs:

- shortlist;
- `/info` read-only snapshots;
- previous local snapshots;
- all mids;
- fills and open orders.

Logic:

- open orders are context only;
- fills and position deltas are stronger evidence;
- ambiguous flips stay `UNKNOWN`;
- `edge_remaining_bps` is mandatory;
- copy degradation includes delay, spread, slippage, fees, liquidity and penalties;
- paper sizing requires leader account value and leader position notional.

Output:

- `leader_snapshots`;
- `fill_snapshots`;
- `open_order_snapshots`;
- `leader_deltas`;
- `copy_signal_candidates`;
- `no_trade_decisions`;
- local `PaperIntent`/`PaperTrade` only if every gate passes.

### Job C: Reports / Dashboard

Outputs:

- no-trade JSON/Markdown/CSV;
- copy run JSON;
- dashboard HTML;
- archive/runtime/safety audits.

## What Was Implemented From This Research

- Ratio-based paper sizing: follower equity / leader equity.
- Local max notional cap.
- Local minimum notional refusal.
- Blocked asset refusal.
- Refusal if leader equity is missing.
- Refusal if leader position notional is unmeasurable.
- no-trade explanations for all sizing refusal paths.
- Adverse price-move penalty for late copy attempts: `OPEN_LONG` is penalized
  when current mid is above the leader price; `OPEN_SHORT` is penalized when
  current mid is below the leader price.
- Tests for proportional sizing, caps, missing data and blocked assets.

## What Is Explicitly Not Implemented

- No live order placement.
- No IOC order.
- No market or limit order.
- No Hyperliquid `/exchange`.
- No private key handling.
- No signing.
- No mainnet.
- No active testnet executor.
- No "guaranteed profit" claim.

## Next Safe Implementation Steps

1. Import a real 1-3 wallet shortlist with complete addresses and metrics.
2. Run one bounded `/info` copy-run on that shortlist.
3. Compare resulting deltas and no-trade reasons.
4. Enrich `leader_account_value` and per-coin metadata from `clearinghouseState`/`meta`.
5. Add paper close/reduce following from leader deltas, still local only.
6. Add dashboard columns for paper notional, copy ratio and sizing refusal reasons.

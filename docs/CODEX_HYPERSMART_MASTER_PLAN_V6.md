# CODEX_HYPERSMART_MASTER_PLAN_V6

This compatibility document preserves the V6 master-plan entrypoint expected by
the test suite and by older Codex/Claude handoffs.

Current source of truth:

- `docs/CODEX_HYPERSMART_MASTER_PLAN_V7_ACTION_BOUNDARY.md`

V7 replaces the overly strict V6 interpretation while preserving the useful V6
history below its `HISTORIQUE V6 CONSERVE CI-DESSOUS` section.

Core doctrine:

- HyperSmart is Hyperliquid-first.
- Runtime remains local simulation / paper only.
- Use read-only Hyperliquid data paths for research, scanning, backtests and UI.
- `/exchange` is named here only as a forbidden endpoint: no operational
  `/exchange` calls, no real orders, no signatures, no private keys, no wallet
  connect.
- No fake PnL, no fake chart, no fake position.
- Score is not signal. Paper trade is not order. Historical PnL is not future
  profit.

Required preserved V6 ticket anchors:

## Ticket 05 - MarketSignalFeatures V5

Preserved in V7 as `TICKET 05 - MarketSignalFeatures V5`.
Purpose: build market features from read-only Hyperliquid data such as
`allMids`, `l2Book`, public trade flow, spread, liquidity and volatility.

## Ticket 17 - Dashboard V3 vivant

Preserved in V7 as `TICKET 17 - Dashboard V3 vivant`.
Purpose: display the official local simulation, paper PnL, source health,
decision evidence and no-trade reasons without fake data or external action.

## Ticket 22 - Polymarket/Kalshi/dYdX boundaries

Preserved in V7 as `TICKET 22 - Polymarket/Kalshi/dYdX boundaries`.
Purpose: keep non-Hyperliquid sources as research/benchmark ideas only, while
HyperSmart runtime stays Hyperliquid read-only plus local simulation.

For implementation work, read V7 first and treat it as authoritative.

# HyperSmart GitHub / Hyperliquid Deep Rescan V6

Date: 2026-06-18  
Scope: Hyperliquid-only, read-only runtime, local paper/mock USDC simulation.

This document records the V6 rescan so future agents do not re-import unsafe
runtime ideas. External repositories are inspiration only. No external trading
code was copied into HyperSmart.

## Official Hyperliquid Contract

| Source | Verified | HyperSmart adaptation |
|---|---:|---|
| Hyperliquid Info endpoint docs | Yes | `/info` is the only REST runtime surface. Keep `allMids`, `l2Book`, `clearinghouseState`, `userFills`, `userFillsByTime`, `openOrders`, `frontendOpenOrders`, `candleSnapshot` read-only. |
| Hyperliquid WebSocket subscription docs | Yes | WS is read-only, shortlist bounded, max 10 user-specific users, snapshot/update dedupe required. |
| Hyperliquid rate limits and user limits | Yes | Time-range pagination must be bounded. `userFillsByTime` is cursor-safe, no infinite scan, no rate-limit bypass. |
| Hyperliquid Exchange endpoint docs | Yes | `/exchange` is the action/signature/order surface and remains audit-banned. |

Primary docs checked:

- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint

## Repository Idea Matrix

| Repo | Status | Keep | Adapt to HyperSmart | Ban / Defer |
|---|---|---|---|---|
| `alsk1992/CloddsBot` | Verified by Browser title/page | Decision ledger, diagnostics, local reports, modular risk discipline | Append-only `decision_ledger`, source health, dashboard/audit reports | Execution, credentials, live trading, profit claims |
| `HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits` | Plan-reviewed | One core, one risk layer, adapter thinking | Read-only venue adapters, one RiskEngine, paper-only core | Real order execution, market-making, fast execution promises |
| `MrFadiAi/Polymarket-bot` | Plan-reviewed | WalletScoreV2, copyability, one-big-win and drawdown filters | Hyperliquid wallet intelligence, conservative paper sizing | Private key, live toggle, auto-copy real |
| `lihanyu81/polymarket_lp_tool` | Plan-reviewed | WS-first, REST reconcile, cooldown, structured tracing | Hyperliquid WS shortlist + REST reconciliation + JSONL decisions | Order manager, cancel/repost/reprice |
| `yangyuan-zhen/PolyWeather` | Plan-reviewed | Authoritative dashboard snapshot, stale-state honesty | Dashboard must show stale/empty states without invented data | Payments/onchain runtime |
| `Composio-HQ/polymarket-kalshi-arbitrage-bot` | Plan-reviewed | `/health`, `/status`, scanner/no-trade current state | Local read-only status and source health | Private key, proxy wallet, CLOB, buy actions |
| `aarora4/Awesome-Prediction-Market-Tools` | Plan-reviewed | Product benchmark: analytics, leaders, alerts, exports | Hyperliquid dashboard coverage map | Wallet integrations, one-click replication |
| `NYTEMODEONLY/polyterm` | Plan-reviewed | Agent-safe manifests, read-only tools, local SQLite, exports | HyperSmart read-only agent manifest and schemas | Write/trade tools |
| `txbabaxyz/mlmodelpoly` | Plan-reviewed | Market features: OHLCV, CVD, VWAP, volatility, edge logger | `market_signals` from `allMids`, `l2Book`, `candleSnapshot`, future trades | Binance/Polymarket hot-path dependencies |
| `txbabaxyz/polyrec` | Plan-reviewed | Rich CSV/JSON features, orderbook depth, ATR/RVOL, backtest exports | `scan_features` with feature hashes and source refs | Logs as primary DB, non-Hyperliquid runtime |
| `evan-kolberg/prediction-market-backtesting` | Plan-reviewed | Event replay, no-lookahead, fees/slippage/latency, equity/drawdown | Runtime/backtest parity tests and reports | Code copying / license contamination |
| `ent0n29/polybot` | Plan-reviewed | Architecture boundaries, analytics/monitoring discipline | SQLite-local interfaces only | ClickHouse/Kafka/Grafana/executor-service now |
| `Polymarket/agents` | Plan-reviewed | Typed evidence/research reports | Offline/read-only DecisionExplainer concept | CLOB, signing, autonomous bets |
| `tradingview/lightweight-charts` | Plan-reviewed | Fast financial charts | Real paper equity/edge/degradation charting only | Fake chart movement |

## What Was Implemented From This Rescan

- `copy-run` now carries richer live market features into the decision path:
  `allMids`, `l2Book`, and read-only `candleSnapshot` volatility context.
- Runtime scan features export includes realized/range/ATR volatility, bucket,
  data quality, and source timestamp.
- `decision_ledger` is now written by the core `run_copy_dry_run()` path, not
  only by the CLI wrapper.
- Ledger entries link decisions to `feature_hash` when a market feature was
  available, plus source refs (`allMids`, `l2Book`, `candleSnapshot`) and
  reason codes.
- Accepted local paper simulations are linked back into the ledger with
  `paper_intent_id` and `paper_trade_id`, preserving the "paper trade is not an
  order" evidence chain.
- Leader `REDUCE` / `CLOSE_LONG` / `CLOSE_SHORT` deltas are now routed to the
  existing local `PaperTradingSimulator.close_paper_trade` path after the
  collection transaction commits, avoiding SQLite nested-write locks.
- Exit decisions are recorded in the same decision-ledger format with
  `PAPER_EXIT_CLOSE`, `PAPER_EXIT_REDUCE` or `PAPER_EXIT_NO_TRADE`,
  `exit_trigger`, `exit_reference_price`, `paper_trade_id` and
  `realized_net_pnl`.
- The read-only dashboard now renders the latest decision ledger with feature
  hashes, reason codes, raw refs, paper ids and exit PnL fields.

## Explicit Non-Adaptations

- No scraping/proxy/rate-limit bypass.
- No Polymarket/Kalshi runtime.
- No CLOB integration.
- No `/exchange`.
- No signing, private key, wallet connect, real order, or mainnet/testnet
  execution.
- No claim that paper/backtest PnL predicts future profit.

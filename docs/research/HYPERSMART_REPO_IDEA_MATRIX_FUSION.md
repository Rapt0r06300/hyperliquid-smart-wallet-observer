# HyperSmart Repo Idea Matrix Fusion

## Objectif

Fusionner les idees utiles des depots externes dans HyperSmart sans importer de
code externe. Cette matrice classe chaque idee en KEEP, ADAPT_TO_HYPERLIQUID,
BAN ou DEFER, puis la rattache a un module local, une donnee Hyperliquid
read-only et un test attendu.

## Source GitHub inspiratrice

- CloddsBot: https://github.com/alsk1992/CloddsBot
- Harrier toolkits: https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits
- MrFadiAi Polymarket-bot: https://github.com/MrFadiAi/Polymarket-bot
- polymarket_lp_tool: https://github.com/lihanyu81/polymarket_lp_tool
- PolyWeather: https://github.com/yangyuan-zhen/PolyWeather
- Composio arbitrage bot: https://github.com/Composio-HQ/polymarket-kalshi-arbitrage-bot
- Awesome Prediction Market Tools: https://github.com/aarora4/Awesome-Prediction-Market-Tools
- PolyTerm: https://github.com/NYTEMODEONLY/polyterm
- mlmodelpoly: https://github.com/txbabaxyz/mlmodelpoly
- polyrec: https://github.com/txbabaxyz/polyrec
- prediction-market-backtesting: https://github.com/evan-kolberg/prediction-market-backtesting
- polybot: https://github.com/ent0n29/polybot
- Polymarket agents: https://github.com/Polymarket/agents
- Lightweight Charts: https://github.com/tradingview/lightweight-charts

## Adaptation Hyperliquid

HyperSmart reste Hyperliquid-first et read-only. Toute idee issue de Polymarket,
Kalshi, dYdX, Binance, Nautilus ou autre venue est convertie vers `/info`, WS
read-only, SQLite local, DecisionLedger explicable, et simulation paper/mock
USDC. Aucun chemin d'execution, signature, cle privee ou CLOB n'est adapte.
`openOrders` seuls restent du contexte et ne creent jamais un `PaperIntent`.

## Matrice KEEP / ADAPT_TO_HYPERLIQUID / BAN / DEFER

| Repo | KEEP | ADAPT_TO_HYPERLIQUID | BAN | DEFER | Modules cibles | Donnees HL | Tests requis | Statut |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CloddsBot | dashboard local, reports/artifacts, diagnostics, doctor, ledger hash, whale/copy tracking, telemetry, SQLite | Transformer le WebChat trading en console observer read-only avec DecisionLedger et diagnostics source health | order execution, credentials, payments, token launch, live trading, DCA/copy execution reel | agent marketplace | `dashboard/exporter.py`, `audit/*`, `copy_mode/*`, `storage/*` | `allMids`, `l2Book`, `userFillsByTime`, `clearinghouseState` | `test_hypersmart_dashboard_readonly.py`, `test_hypersmart_audit_safety.py` | PARTIAL |
| Harrier toolkits | adapter commun, risk layer unique, rate limiter, circuit breaker, depth guard, cooldown | "One observation/paper core. One risk layer. Every venue." avec HyperliquidAdapter prioritaire et DydxAdapter secondaire/mockable | FAK/GTD reels, market making, resolution sniper, sports execution, TP/SL reel, execution <50ms, enable_trading | venue expansion non-HL | `hyperliquid_client/*`, `data_sources/provider_registry.py`, `risk_engine/*` | `allMids`, `l2Book`, `bbo`, `userRateLimit` | `test_hypersmart_rate_limiter.py`, `test_risk_engine.py` | PARTIAL |
| MrFadiAi Polymarket-bot | winrate, profit factor, consistency, one_big_win_ratio, pnl_concentration, mock halts, conservative sizing | WalletScoreV2 et CopyabilityScore calcules sur fills HL; halts uniquement paper portfolio | private key, wallet verification reel, live toggle, panic sell, real balances, DRY_RUN=false | none | `scoring/*`, `copy_mode/sizing.py`, `paper_trading/*`, `simulation/*` | `userFillsByTime`, `userFills`, `clearinghouseState` | `test_hypersmart_anti_luck_filters.py`, `test_hypersmart_copy_sizing.py` | PARTIAL |
| polymarket_lp_tool | WS-first, REST reconciliation, dedupe, structured tracing, source health, mid stability, EMA/median smoothing, cooldown | Convertir order manager en dedupe/reconciliation/no-trade; openOrders restent contexte | cancel/repost/reprice, post-only, ordre reel | old Python only as concept reference | `realtime_monitor/*`, `copy_mode/snapshot_engine.py`, `storage/repositories.py` | WS `allMids`, `l2Book`, `trades`, REST `allMids`, `l2Book` | `test_hypersmart_ws_dedupe.py`, `test_no_open_orders_only_paper_intent.py` | PARTIAL |
| PolyWeather | event-driven dashboard, authoritative snapshot, stale blocked, fallback refresh, health/status/metrics, runtime data outside git | `DashboardPayload` et stale policy: un signal stale n'est jamais paper-ready | payments, onchain checkout, reward points | browser extension ideas | `dashboard/*`, `ui/routes.py`, `storage/models.py` | source health over `allMids`, `l2Book`, `userFillsByTime` | `test_hypersmart_dashboard_readonly.py`, `test_dashboard_stale_signal_not_paper_ready.py` | PARTIAL |
| Composio arbitrage bot | `/health`, `/status`, scanner_running, current_signal/no_trade, timing gates, spread/edge metrics | Status read-only et current candidate/no-trade sans action trade | private key, proxy wallet, trade USD, CLOB, ethers, buy_polymarket, tradingEnabled=true | arbitrage execution | `app/main.py`, `ui/routes.py`, `copy_mode/no_trade_report.py` | `allMids`, `l2Book`, `source_health` | `test_hypersmart_runtime_check.py`, `test_no_polymarket_clob_or_private_key_imports.py` | PARTIAL |
| Awesome Prediction Market Tools | wallet analytics, leaderboards, copyability, smart/whale/suspicious/fresh flags, live mids/spreads/liquidity/depth | Product benchmark for premium HyperSmart dashboard and labels | one-click replication, autonomous betting agents, wallet integration, fake products, Telegram trading | alerts default off | `wallet_discovery/*`, `dashboard/*`, `scoring/*` | `clearinghouseState`, `userFillsByTime`, `allMids`, `l2Book` | `test_hypersmart_wallet_intelligence.py`, `test_ui_leaderboard.py` | PARTIAL |
| PolyTerm | TUI/agent-ready tooling, manifest, JSON schemas, doctor, SQLite, CSV/JSON export, replay, zero custody risk | Agent-safe read-only manifest with only read/export/search/status tools | trade links, Kelly real sizing, write/trade tools | 73+ screens as inspiration | `agent_tools/*`, `dashboard/exporter.py`, `backtesting/*` | local SQLite, `source_health`, `decision_ledger` | `test_agent_safe_manifest_readonly_only.py` | DONE |
| mlmodelpoly | WS streams, OHLCV, CVD, VWAP, volatility, fair value, edge, latest/features, decision_logger | Feature rows over HL book/mids/trades; no Binance latency arb | Binance->Polymarket latency arb, Polymarket CLOB, TAAPI secret hot path | TUI extras | `market_signals/*`, `copy_mode/edge.py`, `dashboard/*` | WS `trades`, `bbo`, `l2Book`, `allMids`, `candleSnapshot` | `test_market_signal_features_rich_export_schema.py` | PARTIAL |
| polyrec | rich CSV, timestamps, returns, orderbook levels, spread, imbalance, microprice, slope, backtesting | `scan_features` CSV/JSON per run from HL L2 and mids | Chainlink/Binance/Polymarket execution, logs as primary DB | specialized BTC 15m assumptions | `market_signals/orderbook_features.py`, `market_signals/exporter.py`, `copy_mode/copy_loop.py`, `backtesting/*` | `l2Book`, `allMids`, `candleSnapshot`, `trades` | `test_l2book_liquidity_score.py`, `test_scan_features_csv_json_export_per_run.py`, `test_copy_run_network_read_collects_snapshots_deltas_signals_and_paper.py` | DONE |
| prediction-market-backtesting | adapters, staged loading, caches, replay, equity/PnL/drawdown/Sharpe, fees/slippage/latency/liquidity/no-trade | Same Common Data Model, RiskEngine, EdgeCalculator and PaperEngine in runtime and replay | code copy, mixed-license contamination, live sandbox path | Nautilus internals | `backtesting/replay_engine.py`, `backtesting/runtime_parity.py` | cached fills, book deltas, trades, source health | `test_backtest_runtime_parity_same_models.py` | PARTIAL |
| polybot | ingestion/strategy/analytics/monitoring separation, replication scoring, calibration | Keep as architecture note only for future scale | executor-service, live mode, private keys, market making | ClickHouse, Redpanda/Kafka, Grafana, Prometheus, microservices | `docs/*`, future `pipeline/*` | future archive/local events only | `test_repo_idea_matrix_has_keep_adapt_ban_defer.py` | DEFER |
| Polymarket agents | connector separation, Pydantic models, RAG/evidence reports | Offline research layer only; never hot path decision | private key, CLOB, signing orders, autonomous trading, operational `trade.py` | Chroma-like docs indexing | `docs/research/*`, future `research/*` | documentation and local evidence only | `test_no_llm_hot_path_policy.py` | DEFER |
| Lightweight Charts | performant financial charting, time series | Use for metagraph, paper equity, edge, source latency, spread/liquidity charts from real rows only | fake movement, synthetic chart data | advanced drawing tools | `src/hl_observer/ui/static/*`, `dashboard/*` | SQLite snapshots, source health, decision ledger, `scan_features` exports | `test_no_fake_chart_or_fake_position_data.py`, `test_dashboard_reads_latest_scan_features_export.py` | PARTIAL |

## Modules cibles

- Existing equivalents: `hyper_smart_observer/hyperliquid_client`, `hyper_smart_observer/copy_mode`, `hyper_smart_observer/storage`, `hyper_smart_observer/realtime_monitor`, `src/hl_observer/hyperliquid`, `src/hl_observer/storage`, `src/hl_observer/ui`, `src/hl_observer/edge`, `src/hl_observer/wallets`.
- New docs map names like `venues/`, `pipeline/`, `market_signals/` to these equivalents unless implementation creates a non-duplicative wrapper.

## Donnees Hyperliquid utilisees

Read-only only: `/info` `allMids`, `l2Book`, `clearinghouseState`,
`userFills`, `userFillsByTime`, `openOrders`, `frontendOpenOrders`,
`orderStatus`, `candleSnapshot`; WS `allMids`, `userFills`, `userEvents`,
`openOrders`, `clearinghouseState`, `l2Book`, `trades`, `bbo`.

## Tests requis

- Existing proof: `tests/test_audit_bounded_scan.py`, `tests/test_no_open_orders_only_paper_intent.py`, `tests/test_hypersmart_audit_safety.py`, `tests/test_hypersmart_dashboard_readonly.py`, `tests/test_hypersmart_collector_readonly.py`, `tests/test_hypersmart_risk_gates.py`.
- Fusion tests to add: docs existence, matrix classifications, license safety markers, no exchange/private-key/live toggle, no fake data/profit promise, agent-safe manifest read-only.

## Statut DONE / PARTIAL / TODO / DEFER / BAN

Overall status: PARTIAL. Safety and openOrders-only proof are DONE. PS1 freshness guard is DONE. Docs matrix, agent-safe manifest, MarketMid fallback, l2Book features, rich market feature export, bounded `copy-run` `scan_features` CSV/JSON export, static dashboard `scan_features` display, Common Data Model metadata audit, WS snapshot dedupe, hot watch max 10 unique users, paper-intent deny-by-default tests and backtest/runtime parity contract are DONE for this fusion pass. Polybot scale and Polymarket agents RAG remain DEFER. All execution paths listed as BAN remain forbidden.

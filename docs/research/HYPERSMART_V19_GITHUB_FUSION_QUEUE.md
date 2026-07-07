# HyperSmart V19 - GitHub fusion queue

Cette file transforme la recherche GitHub en travaux codables, testables et locaux.

Important: elle ne promet pas de PnL positif. Elle force seulement une fusion disciplinee: signal -> risque -> PaperEngine -> evidence -> tests.

| Rang | Repo | Priorite | Action | Module cible | Test obligatoire | Idees a porter |
|---:|---|---|---|---|---|---|
| 1 | [hummingbot](https://github.com/hummingbot/hummingbot) | P0 connector architecture | ADAPTER_CODE_PERMISSIF_AVEC_ATTRIBUTION | `connectors/hyperliquid_readonly.py` | `tests/test_v12_strategy_registry.py` | connector standard<br>strategy controller<br>market making<br>cross-exchange framework |
| 2 | [rustjesty hyperliquid-drift-arbitrage-bot](https://github.com/rustjesty/hyperliquid-drift-arbitrage-bot) | P0 delta-neutral simulation | ADAPTER_CODE_PERMISSIF_AVEC_ATTRIBUTION | `connectors/base.py` | `tests/test_v12_connectors_research.py` | ConnectorBase<br>basis arbitrage<br>depth average price<br>partial fill guard<br>reconciliation |
| 3 | [ChainInsighter Solana-Copy-trading-bot](https://github.com/ChainInsighter/Solana-Copy-trading-bot) | P0 copy session UX | REIMPLEMENTER_PATTERN_VERIFIER_SOURCE | `realtime/latency_report.py` | `tests/test_runtime_session_logs.py` | multi-wallet monitoring<br>latency profiler<br>session controller<br>PnL chart |
| 4 | [freqtrade](https://github.com/freqtrade/freqtrade) | P0 backtesting discipline | REIMPLEMENTER_PATTERN_SANS_COPIER | `optimization/profit_optimizer.py` | `tests/test_v12_no_lookahead_guard.py` | dry-run<br>backtesting<br>hyperopt<br>lookahead analysis<br>strategy configs |
| 5 | [Jackhuang166 hyberliquid-arbitrage-bot](https://github.com/Jackhuang166/hyberliquid-arbitrage-bot) | P0 Hyperliquid arbitrage | REIMPLEMENTER_PATTERN_VERIFIER_SOURCE | `features/basis.py` | `tests/test_v12_source_reconcile.py` | spread scanner<br>symbol normalization<br>orderbook snapshots<br>fees/slippage/liquidity filters |
| 6 | [Rezzecup whale-wallet-mirror-copy-trader](https://github.com/Rezzecup/whale-wallet-mirror-copy-trader) | P0 copy-wallet | REIMPLEMENTER_PATTERN_VERIFIER_SOURCE | `wallets/leader_hotness.py` | `tests/test_hypersmart_v19_repo_coverage.py` | wallet mirror<br>smart money tracker<br>proportional sizing<br>latency tracking<br>wallet journal |
| 7 | [terauss Polymarket-Copy-Trading-Bot](https://github.com/terauss/Polymarket-Copy-Trading-Bot) | P0 hot-path separation | REIMPLEMENTER_PATTERN_VERIFIER_SOURCE | `copying/simulation_pipeline.py` | `tests/test_v9_simulation_pipeline_src.py` | multi-trader monitoring<br>hot_path/research_path split<br>dedupe<br>CSV logging<br>conflicting leaders |
| 8 | [tony-42069 trader-tony-v4](https://github.com/tony-42069/trader-tony-v4) | P0 autonomous product | REIMPLEMENTER_PATTERN_VERIFIER_SOURCE | `signals/entry_quality_gate.py` | `tests/test_v15_entry_quality.py` | autonomous scan<br>risk flags<br>dashboard<br>SL/TP/trailing<br>manipulation flags |
| 9 | [alsk1992 CloddsBot](https://github.com/alsk1992/CloddsBot) | P1 risk/calibration | ADAPTER_CODE_PERMISSIF_AVEC_ATTRIBUTION | `calibration/confidence_buckets.py` | `tests/test_v13_calibration_explainer.py` | confidence calibration<br>VaR/CVaR<br>shadow promotion<br>journal<br>secure report |
| 10 | [HarrierOnChain Prediction-Markets-Trading-Bot-Toolkits](https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits) | P1 microstructure | ADAPTER_CODE_PERMISSIF_AVEC_ATTRIBUTION | `features/orderbook_imbalance.py` | `tests/test_v9_market_features_src.py` | orderbook imbalance<br>direction multi-timeframe<br>depth guard<br>rate budgets |
| 11 | [MrFadiAi Polymarket-bot](https://github.com/MrFadiAi/Polymarket-bot) | P1 smart-money thresholds | ADAPTER_CODE_PERMISSIF_AVEC_ATTRIBUTION | `scoring/smart_money_filter.py` | `tests/test_v12_wallet_score_cluster.py` | smart-money thresholds<br>daily/monthly halts<br>adaptive sizing<br>trade floor |
| 12 | [tradingview lightweight-charts](https://github.com/tradingview/lightweight-charts) | P1 charts | ADAPTER_CODE_PERMISSIF_AVEC_ATTRIBUTION | `ui/static/charts_lwc.js` | `tests/test_v12_chart_series.py` | incremental series.update<br>price lines<br>markers<br>low-jank charts |
| 13 | [Drakkar-Software Triangular-Arbitrage](https://github.com/Drakkar-Software/Triangular-Arbitrage) | P1 graph arbitrage | REIMPLEMENTER_PATTERN_SANS_COPIER | `strategies/library.py` | `tests/test_v12_strategy_library.py` | graph cycles<br>path detection<br>fees<br>ignored symbols<br>multi-exchange abstraction |
| 14 | [evan-kolberg prediction-market-backtesting](https://github.com/evan-kolberg/prediction-market-backtesting) | P1 backtest quality | REIMPLEMENTER_PATTERN_VERIFIER_SOURCE | `backtest/experiment_runner.py` | `tests/test_v12_backtest_experiment.py` | ledger replay<br>book replay<br>Brier<br>experiment runner<br>optimization caveats |
| 15 | [gajesh2007 funding-arb-bot](https://github.com/gajesh2007/funding-arb-bot) | P1 funding | REIMPLEMENTER_PATTERN_VERIFIER_SOURCE | `features/funding.py` | `tests/test_v13_dip_emos_deb.py` | funding scanner<br>2 sigma spike<br>max hold<br>drawdown kill switch<br>drift detection |
| 16 | [notlelouch ArbiBot](https://github.com/notlelouch/ArbiBot) | P1 low latency | REIMPLEMENTER_PATTERN_VERIFIER_SOURCE | `realtime_monitor/ws_supervisor.py` | `tests/test_v12_ws_supervisor_provenance.py` | low-latency websocket<br>event-time ordering<br>bounded event queue<br>graceful shutdown |

## Definition of done par repo

Chaque item est considere integre seulement si:

- le module cible contient une adaptation Hyperliquid/local-paper du pattern;
- le test obligatoire passe;
- la decision apparait dans l'evidence_chain ou le no-trade ledger;
- la simulation n'utilise aucune donnee fake et aucun ordre externe;
- le PnL reste un resultat mesure, jamais une garantie.

queue_count=16
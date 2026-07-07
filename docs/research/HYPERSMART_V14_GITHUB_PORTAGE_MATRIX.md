# HyperSmart V14 - matrice de portage GitHub vers Hyperliquid paper

Cette matrice suit la V14 : on ne copie pas des depots entiers, on porte leurs
idees produit et leurs reglages vers HyperSmart, en lecture seule Hyperliquid et
simulation locale uniquement.

| Repo | Original logic | Hyperliquid port | Module(s) | Config | Test(s) | Dashboard | Status |
|---|---|---|---|---|---|---|---|
| Rezzecup/whale-wallet-mirror-copy-trader | Whale wallet mirror, slippage, sizing proportionnel | LeaderDelta -> MirrorCandidate -> PaperIntent | `src/hl_observer/copy_mode/wallet_mirror_runtime.py`, `src/hl_observer/risk/proportional_paper_sizer.py`, `src/hl_observer/paper_trading/mirror_paper_executor.py` | `HYPERSMART_MIRROR_COPY_RATIO`, max notional, slippage | `tests/test_v14_wallet_mirror_runtime.py` | `src/hl_observer/ui/wallet_mirror_panel.py` | PARTIAL: vertical slice paper disponible |
| terauss/Polymarket-Copy-Trading-Bot | Hot path leger + research/logging separes | Hot path no LLM + JSONL/CSV evidence | `src/hl_observer/runtime/hot_path.py`, `src/hl_observer/exports/csv_logging.py`, `src/hl_observer/market_signals/market_cache.py` | TTL cache, no heavy import | A completer V14 framework tests | Dashboard lit les caches existants | PARTIAL |
| ChainInsighter/Solana-Copy-trading-bot | Session control, latency, copy settings | Controle session local-only + latency profiler | `src/hl_observer/copy_mode/copy_session_controller.py`, `src/hl_observer/copy_mode/copy_latency_profiler.py` | local-only | A completer | Panneaux copy existants | PARTIAL |
| Immutal0/Solana-CopyTrading-Bot | Multi-wallet, subscriptions, conflicts | Max users shortlist + conflit leaders | `src/hl_observer/copy_mode/wallet_subscription_planner.py`, `src/hl_observer/signals/copy_conflict_resolver.py`, `src/hl_observer/copy_mode/multi_wallet_copy_session.py` | max unique users | `tests/test_v14_wallet_mirror_runtime.py` | Copy status | PARTIAL |
| Neron888/Polymarket-copy-trading-bot | UX simple copy bot | Vue simple via status simulation/read-only | `src/hl_observer/ui/routes.py`, `src/hl_observer/ui/static/simulation_v2.html` | paper only | tests UI existants | Simulation existante | PARTIAL |
| tony-42069/trader-tony-v4 | Risk flags marche | Spread/liquidity/manipulation flags | `src/hl_observer/risk/abnormal_spread_detector.py`, `src/hl_observer/risk/suspicious_liquidity_detector.py`, `src/hl_observer/risk/market_manipulation_flags.py` | spread/liquidity thresholds | A completer | Risk panel existant | PARTIAL |
| freqtrade/freqtrade | Dry-run, pairlist, backtest, hyperopt, lookahead | Coin universe + local optimizer + no lookahead wrappers | `src/hl_observer/universe/coin_universe.py`, `src/hl_observer/backtesting/lookahead_analysis.py`, `src/hl_observer/backtesting/hyperopt_local.py` | local optimizer only | A completer | Backtest panels existants | PARTIAL |
| drakkar-software/octobot | Strategy catalog, paper trading, local AI options | Strategy profiles + Ollama offline advisor | `src/hl_observer/strategies/v14_profiles.py`, `src/hl_observer/research/ollama_client.py`, `src/hl_observer/research/ollama_advisor.py` | `HYPERSMART_V13_OLLAMA_*`, `OLLAMA_BASE_URL` | `tests/test_v14_ollama_integration.py` | IA decisions panel | DONE for safe Ollama port |
| hummingbot/hummingbot | Connector architecture, market-making/arbitrage paper | Read-only/paper connector style | `src/hl_observer/connectors/*`, `src/hl_observer/paper_trading/paper_connector.py` | paper connector only | V12 connector tests | Dashboard source health | PARTIAL |
| JLowo/gengar_polymarket_bot | Kelly, margin of safety, calibration, pending/ghost fills | Kelly capped + margin of safety + calibration reports | `src/hl_observer/risk/kelly_sizer.py`, `src/hl_observer/edge/margin_of_safety.py`, `src/hl_observer/calibration/*` | Kelly disabled by default | A completer | Model panel | PARTIAL |
| djienne/Polymarket-bot | Dual strategy, optimizer, health, graceful shutdown | Strategy registry + local optimization + lifecycle | `src/hl_observer/strategies/*`, `src/hl_observer/backtesting/hyperopt_local.py` | offline only | A completer | Strategy panels | PARTIAL |
| Jonmaa/btc-polymarket-bot | Time-window strategy | Windowed signals/backtests concept already in freshness modules | `src/hl_observer/freshness/*`, `src/hl_observer/backtest/*` | window freshness | Existing freshness tests | Simulation status | PARTIAL |
| CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot | Cross-source arb dashboard/cost bars | Cross-source comparison paper only | `src/hl_observer/arbitrage/cross_source_comparator.py`, `src/hl_observer/arbitrage/opportunity_model.py` | require two sources | A completer | Future arb panel | PARTIAL |
| Jackhuang166/hyberliquid-arbitrage-bot | Hyperliquid/CEX spread/funding scanner | Funding-adjusted paper opportunity ranking | `src/hl_observer/arbitrage/funding_adjusted_edge.py`, `src/hl_observer/arbitrage/opportunity_ranker.py` | min net edge | A completer | Future arb panel | PARTIAL |
| rustjesty/hyperliquid-drift-arbitrage-bot | Delta-neutral dual-leg arb | Delta-neutral paper model + hedge reconciliation | `src/hl_observer/paper_trading/delta_neutral_position.py`, `src/hl_observer/paper_trading/hedge_reconciliation.py` | no real leg | A completer | Future funding panel | PARTIAL |
| gajesh2007/funding-arb-bot | Funding windows, spike, exits | Funding window stats, spike, max hold/divergence/drift | `src/hl_observer/funding/*`, `src/hl_observer/risk/max_hold_exit.py`, `src/hl_observer/risk/price_divergence_exit.py`, `src/hl_observer/risk/drift_detection.py` | funding thresholds | A completer | Future funding panel | PARTIAL |
| notlelouch/ArbiBot | Low-latency multi-source WS | WS supervisor/read-only and event ordering foundation | `src/hl_observer/realtime_monitor/ws_supervisor.py`, `src/hl_observer/runtime/hot_path.py` | bounded WS | Existing WS tests | Source health | PARTIAL |
| Drakkar-Software/Triangular-Arbitrage | Graph/cycles | Triangular graph detector after costs | `src/hl_observer/arbitrage/triangular_graph.py`, `src/hl_observer/arbitrage/triangular_opportunity_detector.py`, `src/hl_observer/arbitrage/path_cost_model.py` | after fees/costs | A completer | Future arb panel | PARTIAL |
| enarjord/passivbot | Futures protections, optimizer, monitor | Equity hard stop, monitor output | `src/hl_observer/risk/equity_hard_stop_loss.py`, `src/hl_observer/monitoring/monitor_output.py` | drawdown caps | A completer | Runtime monitor | PARTIAL |
| pydevtop/interexchange-arbitrage-bot | ROI/volume/volatility screener, can-buy amount | Liquidity/can-buy simulation | `src/hl_observer/paper_trading/can_buy_amount_simulator.py`, `src/hl_observer/market_data/market_matcher.py` | l2 depth | A completer | Future scanner panel | PARTIAL |
| ramilexe/crypto-arbitrage-bot | Multi-exchange opportunity schema/ranking | Common paper opportunity ranking | `src/hl_observer/arbitrage/opportunity_model.py`, `src/hl_observer/arbitrage/opportunity_ranker.py` | fees/costs | A completer | Future arb panel | PARTIAL |

## IA / Ollama - decision de portage

Les repos et frameworks qui utilisent une IA la placent utilement en:

- assistant de recherche;
- explication de decisions;
- calibration de seuils;
- lecture de logs;
- classification offline;
- reporting.

HyperSmart garde donc cette architecture:

```text
simulation/replay logs
 -> ml/train.py modele local deterministe
 -> research/ollama_client.py
 -> research/local_llm_explainer.py
 -> research/ollama_advisor.py
 -> runtime/ml/explanations_latest.json
 -> dashboard panneau IA
```

L'IA locale n'a pas le droit de creer une position. Elle peut seulement dire:
"voici pourquoi le bot a perdu/refuse, voici les seuils et tests a regarder".


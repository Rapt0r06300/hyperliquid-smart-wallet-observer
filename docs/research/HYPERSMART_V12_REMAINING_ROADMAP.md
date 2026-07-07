# HYPERSMART V12 — RESTE À FAIRE (audit profond roadmap × 14 GitHub, 2026-06-22)

> Méthode : extraction de TOUS les modules/tests nommés de la roadmap (§V10.2 par repo, §V10.7
> stratégies, §V10.8 exécution profonde, §V10.9 dashboard) croisée avec le code réel.
> DÉJÀ FAIT (ne pas refaire) : features microstructure (CVD/VWAP/RVOL/microprice/impulse/basis/ATR/
> depth_slope/liquidation), copy_fidelity (exec_quality/tracking_error), doctor CLI, kill_switch,
> adaptive_sizing, smart_money_filter, watchlist, walk_forward, monte_carlo, runtime_parity,
> ledger_replay, exec_model (queue/maker-rebate/latency), fill_outcomes, sltp, taxonomie NO_TRADE,
> SourceRegistry/RawStore(+SQLite)/CollectionRecorder, lifecycle+LIQUIDATION, copy_decision, funnel.
> Règles : additif, paper-only, read-only, deny-by-default, 0 fake, Hyperliquid défaut, dYdX dormant.

## Vrais manques ajoutés en progression (#120 → #140)

### Stratégies paper (V10.7 — 20/22 manquantes ; copy_follow + market_making_sim faites)
- **#120 S1** fade_impulse, follow_impulse, whale_fill_early, direction_multi_tf
- **#121 S2** mean_reversion, momentum, spread_farm, volatility_breakout, low_vol_scalping
- **#122 S3** cross_source_discrepancy, dca_sim, kelly_sizing, strategy_ensemble, shadow_model, rag_evidence_context

### Backtest profond (repo 11 — replay_engine n'est qu'un stub)
- **#123 BT1** book_replay (L2 depuis deltas) + trade_tick_replay + no-lookahead
- **#124 BT2** data_bus + materialized_cache (bus cache/local/archive/API, staged loading)
- **#125 BT3** runner_contract + experiment runner + multi_wallet_replay (portefeuille joint)
- **#126 BT4** optimize (random-grid + TPE/Optuna optionnel) + report_charts (equity/PnL/DD/Sharpe/monthly/Brier)

### LP-tool — stabilité de signal (repo 04)
- **#127 LP1** midpoint_jump_filter + mid_stability + ema_median_smoother + stable-confirmation
- **#128 LP2** fill cooldown + max_chase_guard + local_rule_store (JSON) + commandes locales

### Temps réel push (repo 05 PolyWeather)
- **#129 W1** SSE /api/events + event_log SQLite + replay missed events
- **#130 W2** authoritative_snapshot + stale_policy + full_refresh_fallback + runtime_state

### Charts (repo 14 TradingView lightweight-charts)
- **#131 C14** ui/charts : equity/drawdown/candle/edge/liquidity/latency + markers positions & NO_TRADE + incremental update

### Simulation profonde / paper (repos 02/03/08/11)
- **#132 P1** paper journal + position_tracking + breach_alerts
- **#133 P2** types d'ordre profonds : market/limit/post-only + time_stop + MAE/MFE

### Connecteurs & research (repo 13 Polymarket/agents)
- **#134 A13a** connectors base + hyperliquid_readonly + public_research (modèles communs)
- **#135 A13b** rag_evidence + decision_explainer + wallet_thesis (contexte only, hot-path inchangé)

### Produit / agent / QA (repos 07/01/08)
- **#136 AW07** feature_matrix benchmark + local_alerts (off) + red_flags/copyability panels
- **#137 CL01** artifacts auto-extract + context_compaction + optional_registry (skills lazy) + CLI secure
- **#138 PT08** agent schemas JSON + jsonl_adapter + screeners presets + docs/llms.txt + tui_status

### Dashboard & activation live (V10.9)
- **#139 DASH** rendre panneaux restants (proxy health, rate budget, cluster, copy fidelity, exec quality, replay/optim, artifacts/exports)
- **#140 PROMO** gate unifié shadow→autoritatif + rendu HTML NO_TRADE/Funnel/Source Health + StrategyRegistry dans la boucle

## DEFER (échelle, non prioritaire — roadmap §polybot)
ClickHouse/Redpanda/Grafana/Prometheus (concepts seulement), WebChat sidebar complet, 73+ écrans TUI.

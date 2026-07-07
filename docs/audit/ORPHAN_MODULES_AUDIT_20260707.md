# Audit modules orphelins — 2026-07-07

Constat: **111 modules** sous `src/hl_observer` ne sont importés NULLE PART
(ni runtime, ni tests). Beaucoup correspondent EXACTEMENT aux tâches de la
feuille de route: le travail y est déjà à moitié fait, il manque test+câblage.
Règle CLAUDE.md rappelée: pas de module isolé sans test ET plan de câblage;
ne rien supprimer brutalement (archiver si obsolète).

Flags: 261 lus dans le code, 61 définis au launcher, 1 flag mort
(`HYPERSMART_ALLOW_MARKET_FLOW_SOLO`, zéro consommateur).

## Triage à faire (WIRE_NOW / TEST_THEN_WIRE / ARCHIVE)

| Module orphelin | Sert la tâche |
|---|---|
| `hl_observer.__main__` | a trier |
| `hl_observer.analysis.entry_edge` | T20/T33 (followability, profit_patterns...) |
| `hl_observer.analysis.exit_edge` | T20/T33 (followability, profit_patterns...) |
| `hl_observer.analysis.followability` | T20/T33 (followability, profit_patterns...) |
| `hl_observer.analysis.opening_outcome` | T20/T33 (followability, profit_patterns...) |
| `hl_observer.analysis.opening_profitability` | T20/T33 (followability, profit_patterns...) |
| `hl_observer.analysis.profit_patterns` | T20/T33 (followability, profit_patterns...) |
| `hl_observer.analysis.trade_lifecycle` | T20/T33 (followability, profit_patterns...) |
| `hl_observer.backtest.monte_carlo` | T29 validation (monte_carlo, replay_engine, runtime_parity) |
| `hl_observer.backtest.replay_engine` | T29 validation (monte_carlo, replay_engine, runtime_parity) |
| `hl_observer.backtest.runtime_parity` | T29 validation (monte_carlo, replay_engine, runtime_parity) |
| `hl_observer.backtest.walk_forward` | T29 validation (monte_carlo, replay_engine, runtime_parity) |
| `hl_observer.backtesting.ab_flag_replay` | T29/T14-17 (ab_flag_replay, hyperopt_local, lookahead DEJA ECRITS) |
| `hl_observer.backtesting.hyperopt_local` | T29/T14-17 (ab_flag_replay, hyperopt_local, lookahead DEJA ECRITS) |
| `hl_observer.backtesting.lookahead_analysis` | T29/T14-17 (ab_flag_replay, hyperopt_local, lookahead DEJA ECRITS) |
| `hl_observer.backtesting.recursive_analysis` | T29/T14-17 (ab_flag_replay, hyperopt_local, lookahead DEJA ECRITS) |
| `hl_observer.cli_pkg_DISABLED.tui_status` | a trier |
| `hl_observer.clusters.cluster_signal_score` | T39 + anti-crowding (wallet_clusterer, crowding_detector) |
| `hl_observer.clusters.crowding_detector` | T39 + anti-crowding (wallet_clusterer, crowding_detector) |
| `hl_observer.clusters.wallet_clusterer` | T39 + anti-crowding (wallet_clusterer, crowding_detector) |
| `hl_observer.collection.l2_snapshot_cache` | T58 profondeur L2 |
| `hl_observer.collection.run_collect_all` | a trier |
| `hl_observer.connectors.connector_base` | T57 multi-venues (connector_base pret) |
| `hl_observer.connectors.market_data_connector` | T57 multi-venues (connector_base pret) |
| `hl_observer.connectors.read_only_market_connector` | T57 multi-venues (connector_base pret) |
| `hl_observer.copy_mode.copy_session_controller` | T54 scanner etages (wallet_subscription_planner DEJA ECRIT) |
| `hl_observer.copy_mode.multi_wallet_copy_session` | T54 scanner etages (wallet_subscription_planner DEJA ECRIT) |
| `hl_observer.copy_mode.wallet_subscription_planner` | T54 scanner etages (wallet_subscription_planner DEJA ECRIT) |
| `hl_observer.copy_wallet.multi_trader_runtime` | a trier |
| `hl_observer.copying.pipeline_integrator` | a trier |
| `hl_observer.core.logging_config` | a trier |
| `hl_observer.core.main` | a trier |
| `hl_observer.dashboard.risk_flags_panel` | a trier |
| `hl_observer.edge.copy_degradation` | a trier |
| `hl_observer.edge.cost_validation` | a trier |
| `hl_observer.edge.tier_cost_budget` | a trier |
| `hl_observer.exits.leader_exit_monitor` | T32 ExitEngine (partial_take_profit, leader_exit_monitor DEJA ECRITS) |
| `hl_observer.exits.partial_take_profit` | T32 ExitEngine (partial_take_profit, leader_exit_monitor DEJA ECRITS) |
| `hl_observer.explorer.explorer_dom_extractor` | a trier |
| `hl_observer.explorer.explorer_rate_budget` | a trier |
| `hl_observer.following.copy_delay` | T18/T19/T20/T54 (copy_delay, shortlist, position_follower DEJA ECRITS) |
| `hl_observer.following.follow_reconciliation` | T18/T19/T20/T54 (copy_delay, shortlist, position_follower DEJA ECRITS) |
| `hl_observer.following.follow_state` | T18/T19/T20/T54 (copy_delay, shortlist, position_follower DEJA ECRITS) |
| `hl_observer.following.leaderboard_follow_shortlist` | T18/T19/T20/T54 (copy_delay, shortlist, position_follower DEJA ECRITS) |
| `hl_observer.following.position_follower` | T18/T19/T20/T54 (copy_delay, shortlist, position_follower DEJA ECRITS) |
| `hl_observer.funding.funding_poller` | T30 paiements reels |
| `hl_observer.gateway.local_source_gateway` | a trier |
| `hl_observer.hyperliquid.ws_client` | T44/T34 (WS client dedie inutilise) |
| `hl_observer.ledger.evidence` | a trier |
| `hl_observer.ml.model_panel` | a trier |
| `hl_observer.optimization.grid_search` | T29 optimiseur (grid/random/walk_forward/tournament DEJA ECRITS) |
| `hl_observer.optimization.hypothesis_engine` | T29 optimiseur (grid/random/walk_forward/tournament DEJA ECRITS) |
| `hl_observer.optimization.profit_report` | T29 optimiseur (grid/random/walk_forward/tournament DEJA ECRITS) |
| `hl_observer.optimization.random_search` | T29 optimiseur (grid/random/walk_forward/tournament DEJA ECRITS) |
| `hl_observer.optimization.strategy_tournament` | T29 optimiseur (grid/random/walk_forward/tournament DEJA ECRITS) |
| `hl_observer.optimization.walk_forward_validator` | T29 optimiseur (grid/random/walk_forward/tournament DEJA ECRITS) |
| `hl_observer.paper.latency_model` | T35 realisme (latency/partial_fill/rejection models DEJA ECRITS) |
| `hl_observer.paper.partial_fill_model` | T35 realisme (latency/partial_fill/rejection models DEJA ECRITS) |
| `hl_observer.paper.rejection_model` | T35 realisme (latency/partial_fill/rejection models DEJA ECRITS) |
| `hl_observer.paper_trading.auto_unstuck` | T32 |
| `hl_observer.paper_trading.can_buy_amount_simulator` | a trier |
| `hl_observer.paper_trading.hedge_reconciliation` | a trier |
| `hl_observer.paper_trading.liquidity_route_simulator` | a trier |
| `hl_observer.paper_trading.v26_exit_pipeline` | T32 |
| `hl_observer.reports.daily_report` | a trier |
| `hl_observer.reports.latency_benchmark_report` | T43 latence |
| `hl_observer.reports.paper_report` | a trier |
| `hl_observer.research.explain_cli` | a trier |
| `hl_observer.research.research_toolkit` | a trier |
| `hl_observer.risk.duplicate_order_guard` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.risk.graded_halt` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.risk.kelly_leader_book` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.risk.kill_switch` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.risk.latency_model` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.risk.position_sizing` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.risk.protections_v26` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.risk.reconciliation_guard` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.risk.slippage_model` | durcissement risk (kill_switch, graded_halt, kelly, slippage_model...) |
| `hl_observer.runtime.graceful_shutdown` | robustesse (graceful_shutdown, safe_mode) |
| `hl_observer.runtime.research_path` | robustesse (graceful_shutdown, safe_mode) |
| `hl_observer.runtime.safe_mode` | robustesse (graceful_shutdown, safe_mode) |
| `hl_observer.scoring.live_wallet_scoring_loop` | T33 scoring live |
| `hl_observer.signals.decisions` | a trier |
| `hl_observer.signals.market_quality_score` | T31 regime/qualite |
| `hl_observer.signals.signal_builder` | a trier |
| `hl_observer.simulation.action_loss_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.coin_loss_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.cost_drag_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.edge_distribution_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.freshness_gates` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.logs_analyzer` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.position_matching_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.profitability_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.refusal_breakdown` | T36 cout des refus (DEJA ECRIT) |
| `hl_observer.simulation.root_cause_from_logs` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.stale_signal_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.timing_distribution_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.simulation.wallet_loss_diagnostics` | T27 audit hebdo (10 modules diagnostics prets) |
| `hl_observer.testnet.testnet_reconciliation` | a trier |
| `hl_observer.ui.wallet_mirror_panel` | a trier |
| `hl_observer.validation.bootstrap` | a trier |
| `hl_observer.validation.testnet_tournament` | a trier |
| `hl_observer.wallets.degradation` | T33/T54 (9 modules wallets) |
| `hl_observer.wallets.leaderboard_dom_extractor` | T33/T54 (9 modules wallets) |
| `hl_observer.wallets.leaderboard_importer` | T33/T54 (9 modules wallets) |
| `hl_observer.wallets.profiler` | T33/T54 (9 modules wallets) |
| `hl_observer.wallets.scan_limits` | T33/T54 (9 modules wallets) |
| `hl_observer.wallets.scan_progress` | T33/T54 (9 modules wallets) |
| `hl_observer.wallets.scan_scheduler` | T33/T54 (9 modules wallets) |
| `hl_observer.wallets.top_wallet_export` | T33/T54 (9 modules wallets) |
| `hl_observer.wallets.toxicity` | T33/T54 (9 modules wallets) |


## Câblage vague 1 — réalisé 2026-07-07

- `ui/refusal_live.py` (nouveau, testé): breakdown LIVE des refus depuis les
  événements ledger en mémoire (raison, part, coins touchés, notional refusé).
  Consommateur prévu: dashboard v2 (T49) — plan de câblage documenté.
- `backtesting.ab_flag_replay`: validé exécutable et déterministe —
  `set PYTHONPATH=src && python -m hl_observer.backtesting.ab_flag_replay --candidates X.jsonl --marks Y.jsonl`
  (bras A vs B sur données enregistrées, prêt pour T14-T17).
- `simulation.refusal_breakdown` (logs): déjà branché au CLI (cli.py:1451) —
  faux orphelin (shim de ré-export), reclassé OK.
- Tests: tests/test_orphan_wiring_wave1.py (4).
- Reste vague 1: funding_poller (T30), latency_benchmark_report (T43),
  l2_snapshot_cache (T58), kill_switch/graded_halt (risk).

## Triage AUDIT-A — mise à jour 2026-07-07 (fin de session)

Orphelins restants: **103** (était 111 ; 8 sortis de la liste car câblés/testés cette session : refusal_live, ab_flag_replay, graded_halt, kill_switch, l2_snapshot_cache walk-the-book, funding_poller, latency_benchmark_report, exits partial/leader).

Classification: WIRE_NOW=1 · TEST_THEN_WIRE=97 · ARCHIVE=5

Règle: aucun module supprimé. WIRE_NOW = brancher maintenant ; TEST_THEN_WIRE = test de contrat d'abord (beaucoup ont reçu leur test cette session via les modules purs) ; ARCHIVE = déplacer hors hot-path sans suppression.

| Module | Classe | Note |
|---|---|---|
| `hl_observer.__main__` | ARCHIVE | outillage/legacy hors hot-path; archiver ou garder en CLI |
| `hl_observer.cli_pkg_DISABLED.tui_status` | ARCHIVE | outillage/legacy hors hot-path; archiver ou garder en CLI |
| `hl_observer.core.main` | ARCHIVE | outillage/legacy hors hot-path; archiver ou garder en CLI |
| `hl_observer.research.explain_cli` | ARCHIVE | outillage/legacy hors hot-path; archiver ou garder en CLI |
| `hl_observer.research.research_toolkit` | ARCHIVE | outillage/legacy hors hot-path; archiver ou garder en CLI |
| `hl_observer.analysis.entry_edge` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.analysis.exit_edge` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.analysis.followability` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.analysis.opening_outcome` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.analysis.opening_profitability` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.analysis.profit_patterns` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.analysis.trade_lifecycle` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.backtest.monte_carlo` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.backtest.replay_engine` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.backtest.runtime_parity` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.backtest.walk_forward` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.backtesting.hyperopt_local` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.backtesting.lookahead_analysis` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.backtesting.recursive_analysis` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.clusters.cluster_signal_score` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.clusters.crowding_detector` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.clusters.wallet_clusterer` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.collection.run_collect_all` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.connectors.connector_base` | TEST_THEN_WIRE | connecteur read-only; à brancher derrière budget API + multi-venues |
| `hl_observer.connectors.market_data_connector` | TEST_THEN_WIRE | connecteur read-only; à brancher derrière budget API + multi-venues |
| `hl_observer.connectors.read_only_market_connector` | TEST_THEN_WIRE | connecteur read-only; à brancher derrière budget API + multi-venues |
| `hl_observer.copy_mode.copy_session_controller` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.copy_mode.multi_wallet_copy_session` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.copy_mode.wallet_subscription_planner` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.copy_wallet.multi_trader_runtime` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.copying.pipeline_integrator` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.core.logging_config` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.dashboard.risk_flags_panel` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.edge.copy_degradation` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.edge.cost_validation` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.edge.tier_cost_budget` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.explorer.explorer_dom_extractor` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.explorer.explorer_rate_budget` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.following.copy_delay` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.following.follow_reconciliation` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.following.follow_state` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.following.leaderboard_follow_shortlist` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.following.position_follower` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.gateway.local_source_gateway` | TEST_THEN_WIRE | connecteur read-only; à brancher derrière budget API + multi-venues |
| `hl_observer.hyperliquid.ws_client` | TEST_THEN_WIRE | connecteur read-only; à brancher derrière budget API + multi-venues |
| `hl_observer.ledger.evidence` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.ml.model_panel` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.optimization.grid_search` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.optimization.hypothesis_engine` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.optimization.profit_report` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.optimization.random_search` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.optimization.strategy_tournament` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.optimization.walk_forward_validator` | TEST_THEN_WIRE | brique d'optimisation/replay; couvrir par test avant orchestration |
| `hl_observer.paper.latency_model` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.paper.partial_fill_model` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.paper.rejection_model` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.paper_trading.auto_unstuck` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.paper_trading.can_buy_amount_simulator` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.paper_trading.hedge_reconciliation` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.paper_trading.liquidity_route_simulator` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.paper_trading.v26_exit_pipeline` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.reports.daily_report` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.reports.paper_report` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.risk.duplicate_order_guard` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.risk.kelly_leader_book` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.risk.latency_model` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.risk.position_sizing` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.risk.protections_v26` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.risk.reconciliation_guard` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.risk.slippage_model` | TEST_THEN_WIRE | brique risque/exécution paper; test de contrat puis câblage gated |
| `hl_observer.runtime.graceful_shutdown` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.runtime.research_path` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.runtime.safe_mode` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.scoring.live_wallet_scoring_loop` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.signals.decisions` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.signals.market_quality_score` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.signals.signal_builder` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.simulation.action_loss_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.simulation.coin_loss_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.simulation.cost_drag_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.simulation.edge_distribution_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.simulation.freshness_gates` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.simulation.logs_analyzer` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.simulation.position_matching_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.simulation.profitability_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.simulation.root_cause_from_logs` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.simulation.stale_signal_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.simulation.timing_distribution_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.simulation.wallet_loss_diagnostics` | TEST_THEN_WIRE | diagnostic atteignable via CLI; test de contrat puis exposer au dashboard |
| `hl_observer.testnet.testnet_reconciliation` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.ui.wallet_mirror_panel` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.validation.bootstrap` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.validation.testnet_tournament` | TEST_THEN_WIRE | à couvrir par test avant décision finale |
| `hl_observer.wallets.degradation` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.wallets.leaderboard_dom_extractor` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.wallets.leaderboard_importer` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.wallets.profiler` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.wallets.scan_limits` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.wallets.scan_progress` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.wallets.scan_scheduler` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.wallets.top_wallet_export` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.wallets.toxicity` | TEST_THEN_WIRE | brique copy/scan; à câbler dans le scanner à étages (livré cette session) |
| `hl_observer.simulation.refusal_breakdown` | WIRE_NOW | outil prêt, à brancher au runtime/dashboard |

## Vague A8 couverte 2026-07-07 (contrats figés)

5 orphelins risque/copy couverts par test de contrat (prêts à câbler): risk.duplicate_order_guard, risk.reconciliation_guard, risk.position_sizing, clusters.crowding_detector, edge.copy_degradation. Test: tests/test_orphan_wave_a8.py. Reste ~98 en TEST_THEN_WIRE, à traiter par vagues.

## Vague B2 couverte 2026-07-07

5 orphelins modeles cout/execution paper couverts (prets a cabler dans le simulateur): risk.slippage_model, risk.latency_model, paper.partial_fill_model, paper.rejection_model, edge.cost_validation. Test: tests/test_orphan_wave_b2.py.

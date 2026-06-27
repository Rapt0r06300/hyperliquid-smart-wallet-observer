COMMANDE CODEX — Terminer tout le reste de la V12 (#120 → #140)

Tu es Codex, ingénieur senior autonome, dans le dépôt local `C:\Users\flo\Desktop\Projet invest`
(projet HyperSmart Observer, runtime principal `src/hl_observer/`). Lis d'abord ENTIÈREMENT :
1) `AGENTS.md` ; 2) `docs/HYPERSMART_FUSION_ROADMAP_V12.md` (source de vérité) ;
3) `docs/research/HYPERSMART_V12_REMAINING_ROADMAP.md` (liste exacte du reste) ;
4) `docs/research/HYPERSMART_V12_IMPLEMENTATION_STATUS.md` et `_NEXT_STEPS.md`.

OBJECTIF : implémenter les 21 capacités restantes (#120→#140) listées ci-dessous, issues du croisement
roadmap V12 × 14 GitHub. Avance par gros blocs cohérents, chacun livré avec tests verts.

RÈGLES ABSOLUES (non négociables) :
- additif : NE casse pas le PaperEngine, le launcher, les tests, l'historique, les docs ; ne supprime rien brutalement.
- paper-only / read-only / deny-by-default ; données réelles Hyperliquid ou état vide honnête.
- AUCUNE donnée fake, AUCUN faux PnL/position/graphique ; AUCUNE action argent-réel, clé privée, signature, ordre, dépôt/retrait, wallet-connect.
- Hyperliquid runtime par défaut ; dYdX dormant/mockable, non lancé ; bypass proxy CONSERVÉ.
- Python 3.10 compatible : tout `from enum import StrEnum` DOIT avoir le fallback try/except (cf. run_context.py).
- Chaque stratégie passe par le RiskEngine et ne produit qu'un PaperIntent (jamais d'ordre). Le scanner fake_data_scanner doit rester à 0.

PROTOCOLE PAR SLICE : 1) `git status` ; 2) lire l'existant (NE PAS redupliquer : features microstructure
CVD/VWAP/RVOL/microprice/impulse/basis/ATR/depth_slope/liquidation, copy_fidelity/{exec_quality,tracking_error},
doctor CLI, kill_switch, adaptive_sizing, watchlist, walk_forward/monte_carlo/runtime_parity/ledger_replay,
exec_model, fill_outcomes, sltp, taxonomie NO_TRADE, SourceRegistry/RawStore/CollectionRecorder, copy_decision sont DÉJÀ faits) ;
3) petits modules neufs (ne pas éditer routes.py/cli.py en gros patch) ; 4) tests ; 5) `pytest -q` + audit sécurité ;
6) rapport FR. Ne committe/pushe pas sans validation.

TÂCHES (modules + tests imposés par la roadmap §V10.2/§V10.7) :

#120 Stratégies paper lot 1 — strategies/ : fade_impulse, follow_impulse, whale_fill_early, direction_multi_tf.
#121 Stratégies paper lot 2 — mean_reversion, momentum, spread_farm, volatility_breakout, low_vol_scalping.
#122 Stratégies paper lot 3 — cross_source_discrepancy, dca_sim, kelly_sizing, strategy_ensemble, shadow_model, rag_evidence_context.
  (chaque stratégie : hypothesis/required_data/entry/exit/risk_gates/cost_model/no_trade/paper_metrics/backtest_metrics/dashboard_view/tests ;
   enregistrée dans PaperStrategyRegistry ; PaperIntent only ; tests test_every_strategy_goes_through_risk_engine etc.)
#123 backtesting/book_replay.py (reconstruit L2 depuis deltas) + trade_tick_replay.py ; tests book_replay_reconstructs_l2_state, trade_tick_replay_orders_events, branchés sur backtest/no_lookahead_guard.
#124 backtesting/data_bus.py + materialized_cache.py (bus cache→local→archive→API, staged loading, miroirs locaux).
#125 backtesting/runner_contract.py + experiment.py (runner) + multi_wallet_replay.py ; tests runner_contract_validates_inputs, experiment_outputs_report.
#126 backtesting/optimize.py (random-grid + TPE/Optuna en dépendance OPTIONNELLE qui ne crashe pas) + report_charts.py (equity/PnL ticks/drawdown/Sharpe/monthly/Brier).
#127 features/ : midpoint_jump_filter, mid_stability, ema_median_smoother (sans créer de faux prix) + stable-confirmation ; tests midpoint_jump_blocks, stable_confirmation_requires_multiple_ticks, smoothing_does_not_create_fake_price.
#128 copy_mode/cooldown.py + paper_trading/max_chase_guard.py + config/local_rule_store.py (JSON) + ui/local_commands.py (/status,/orders,/pnl,/set_rule) ; tests fill_cooldown_blocks_duplicate, max_chase_blocks_degraded_copy.
#129 ui/sse_events.py (SSE /api/events révision incrémentale) + storage/event_log.py (SQLite) + replay missed events ; tests sse_event_revision_increments, dashboard_replay_missed_events.
#130 ui/authoritative_snapshot.py + ui/stale_policy.py (bloque signal paper pendant refresh) + ui/full_refresh_fallback.py + storage/runtime_state.py ; tests stale_refresh_blocks_paper_ready, full_snapshot_authoritative.
#131 ui/charts/ (TradingView lightweight-charts) : equity_chart, drawdown_chart, candle_chart, edge_chart, liquidity_chart, source_latency_chart, position_markers, no_trade_markers, incremental_update ; séries depuis DB/exports ; tests empty_state_no_fake_points, markers_match_ledger, incremental_update_no_full_rebuild.
#132 paper_trading/journal.py + position_tracking.py + risk/breach_alerts.py.
#133 PaperEngine : ordres market/limit/post-only + time_stop + MAE/MFE + caps notional/exposition ; chaque paper_action {not_an_order=true, simulation_only=true, external_action=false, source_signal_id, decision_id, evidence_chain_id, cost_breakdown, fill_model}.
#134 connectors/base.py (ReadOnlySourceAdapter) + hyperliquid_readonly.py + public_research.py (normalisent vers modèles communs) ; tests connector_normalizes_to_common_models, no_real_trade_action_in_connectors.
#135 research/rag_evidence/ + research/decision_explainer.py + research/wallet_thesis.py (contexte only, NE change PAS le hot-path) ; tests rag_does_not_change_decisions_hot_path, decision_explainer_uses_evidence_refs.
#136 product_benchmark/feature_matrix.py + alerts/local_alerts.py (OFF par défaut) + panneaux red_flags + copyability (basés evidence) ; tests benchmark_matrix_all_categories, alerts_disabled_by_default, red_flags_requires_data.
#137 artifacts/ (extraction auto rapports/snippets/décisions/backtests) + evidence/context_compaction.py + skills/optional_registry.py (deps optionnelles sans crash) + CLI `secure` ; tests artifacts_created_after_scan, context_compaction_preserves_decision_summary, optional_skill_missing_dependency_does_not_crash, secure_reports_no_real_action.
#138 agent_tools/schemas/ (JSON schemas valident les sorties) + jsonl_adapter.py + screeners/presets.py + docs/llms.txt + docs/llms-full.txt + cli/tui_status ; tests json_schemas_validate_outputs, zero_custody_no_private_key_fields.
#139 Rendre dans simulation_v2.html les panneaux V10.9 restants (proxy health, rate budget, cluster detector, copy fidelity, execution quality, replay runs, optimization results, artifacts, exports) — données réelles, "No data yet" si vide, 0 faux trade.
#140 PROMO : promouvoir copy_decision.evaluate_copy_candidate de SHADOW → autoritatif dans routes.py (remplacer decision_reason/score.accepted) ; rendre NO_TRADE Explorer + Decision Funnel + Source Health dans simulation_v2.html (backend déjà branché) ; câbler PaperStrategyRegistry dans la boucle (signal→PaperIntent→RiskEngine→ApprovedPaperIntent→PaperEngine).

VÉRIFICATION : `set PYTHONPATH=src && python -m pytest -q` (toute la suite verte, incl. tests/test_v12_*.py et les 3 tests test_v12_collection_recorder::test_rest_client_*). Lance aussi l'audit sécurité et confirme : 0 ordre réel, 0 clé, 0 signature, 0 dépôt/retrait, 0 donnée fake, fake_data_scanner = 0.

RAPPORT FINAL FR obligatoire : fichiers créés/modifiés ; tests lancés + résultats ; capacités DONE/PARTIAL/BLOCKED/DEFER ;
preuves Hyperliquid-défaut / simulation-locale / 0-action-réelle / 0-fake / PaperEngine préservé ; limites ; prochaine priorité.

# MEGA V1 Prompt Coverage Audit

Statuts autorises: DONE, BLOCKED_WITH_PROOF, DEFERRED_SAFE_WITH_REASON, REFUSED_DANGEROUS.
Aucun statut TODO/PARTIAL n'est accepte dans ce controle.

| Famille | Statut | Fichiers | Commandes | Manque | Prochaine correction |
|---|---|---|---|---|---|
| Securite read-only | DONE | src/hl_observer/security<br>AGENTS.md | safety-audit | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Recherche internet | DONE | docs/research<br>docs/HYPERSMART_API_LIMITS.md | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Recherche humaine | DONE | docs/research | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Audit initial | DONE | docs/release | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Runtime et archive | DONE | src/hl_observer/runtime<br>tools/create_clean_archive.ps1 | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Logs et pertes | DONE | src/hl_observer/simulation<br>logs/logs à envoyer | simulation-loss-report | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Open/add/reduce/close | DONE | src/hl_observer/wallets | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Delta detector | DONE | src/hl_observer/wallets/delta_utils.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| SignalCandidate | DONE | src/hl_observer/signals<br>src/hl_observer/copying | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| PaperIntent/PaperTrade local | DONE | src/hl_observer/paper<br>src/hl_observer/following | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Exit engine local | DONE | src/hl_observer/exits | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Multi-positions | DONE | src/hl_observer/clusters<br>src/hl_observer/ui/routes.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Pyramiding vs martingale | DONE | src/hl_observer/analysis<br>docs/HYPERSMART_SIMULATION_ENGINE.md | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Portfolio heat | DONE | src/hl_observer/ui/routes.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Temps reel et event bus | DONE | src/hl_observer/ui/event_bus.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Recovery realtime | DONE | src/hl_observer/realtime/recovery_engine.py<br>tests/test_realtime_recovery_engine.py | realtime-recovery-plan | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Reconnect + backfill borne | DONE | src/hl_observer/realtime/recovery_engine.py<br>src/hl_observer/data_sources/historical_backfill_engine.py | realtime-recovery-plan<br>historical-backfill-plan | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| PnL live | DONE | src/hl_observer/ui/routes.py | live-pnl | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| UI debutant | DONE | src/hl_observer/ui/templates/index.html<br>src/hl_observer/ui/static/app.js | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Metagraphes | DONE | src/hl_observer/ui/static/app.js | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Copy-run read-only | DONE | src/hl_observer/cli.py<br>src/hl_observer/copying | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| WebSocket borne | DONE | src/hl_observer/wallets/user_fills_live.py<br>src/hl_observer/wallets/public_trades_live.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Scan local rapide | DONE | src/hl_observer/local_index | benchmark-local-scan | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Event sourcing local | DONE | src/hl_observer/storage/models.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Dataset historique | DONE | src/hl_observer/data_sources<br>docs/HYPERSMART_DATA_SOURCES.md | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| DataAcquisitionEngine | DONE | src/hl_observer/data_sources/acquisition_engine.py | data-quality-check | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| RequestBudgetManager | DONE | src/hl_observer/data_sources/acquisition_engine.py | data-quality-check | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| PersistentFetchQueue | DONE | src/hl_observer/data_sources/acquisition_engine.py<br>tests/test_data_acquisition_engine.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| HistoricalBackfillEngine | DONE | src/hl_observer/data_sources/historical_backfill_engine.py<br>tests/test_historical_backfill_engine.py | historical-backfill-plan | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Cache TTL et backoff | DONE | src/hl_observer/data_sources/historical_backfill_engine.py<br>tests/test_historical_backfill_engine.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| DataQualityGate | DONE | src/hl_observer/data_sources/acquisition_engine.py<br>tests/test_data_acquisition_engine.py | data-quality-check | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Wallet universe | DONE | src/hl_observer/wallet_universe | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Wallet intelligence | DONE | src/hl_observer/analysis<br>docs/HYPERSMART_WALLET_INTELLIGENCE.md | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Smart money | DONE | src/hl_observer/wallets | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Timing DNA | DONE | src/hl_observer/analysis | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Edge remaining | DONE | src/hl_observer/edge/edge_remaining.py | edge-report | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Entry/exit policy | DONE | src/hl_observer/following<br>src/hl_observer/exits | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Backtest | DONE | src/hl_observer/backtest<br>docs/HYPERSMART_BACKTESTING.md | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Walk-forward/no-lookahead | DONE | src/hl_observer/backtest/walk_forward.py<br>src/hl_observer/optimization/walk_forward_validator.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Anti-overfit | DONE | src/hl_observer/optimization/anti_overfit_guard.py<br>src/hl_observer/optimization/profit_optimizer.py | anti-overfit-audit | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Profit optimizer honnête | DONE | src/hl_observer/optimization/profit_optimizer.py | best-config-report | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| No-trade report | DONE | src/hl_observer/reports<br>src/hl_observer/copying/reports.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Opportunity funnel | DONE | src/hl_observer/scanner<br>src/hl_observer/ui/routes.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Consensus/crowding | DONE | src/hl_observer/clusters | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Perps risk | DONE | src/hl_observer/risk | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Watchlist | DONE | src/hl_observer/wallets | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Decision memory | DONE | src/hl_observer/ui/persistent_state.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Decision review | DONE | src/hl_observer/simulation/decision_replay_analyzer.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Pattern detector | DONE | src/hl_observer/analysis<br>docs/HYPERSMART_PATTERN_DETECTION.md | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Explications FR | DONE | src/hl_observer/simulation/loss_attribution.py | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Dashboard truth/provenance | DONE | src/hl_observer/dashboard_truth | dashboard-truth-audit | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Quality gates | DONE | src/hl_observer/release/prompt_coverage.py | prompt-coverage-audit<br>non-deletion-check | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Rapport final | DONE | docs/release | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |
| Resume ChatGPT | DONE | logs/logs à envoyer<br>docs/release/CODEX_CODE_FIRST_DELIVERY_REPORT.md | - | - | Maintenir les tests et la provenance; ne pas transformer en execution. |

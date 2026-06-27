# Reprise Codex HyperSmart V6

Date: 2026-06-18  
Workspace: `C:\Users\flo\Desktop\Projet invest`  
Plan actif: `docs/CODEX_HYPERSMART_MASTER_PLAN_V6.md`  
Doctrine: Hyperliquid read-only + simulation locale uniquement.

## Etat exact

Le fichier V6 et `AGENTS.md` ont ete lus et traites comme cahier des charges
actif. Le projet n'est pas marque comme termine contre tout le MD: plusieurs
vertical slices sont terminees et testees, mais il reste du travail d'integration
et de QA longue duree.

## Tranches terminees dans cette reprise

1. `copy-run` utilise `allMids`, `l2Book` et `candleSnapshot` pour construire des
   `MarketSignalFeatures` reels avec `feature_hash`.
2. Le ledger de decision est ecrit par le coeur `run_copy_dry_run`, pas seulement
   par la CLI.
3. Les signaux acceptes relient `SignalCandidate -> PaperIntent -> PaperTrade`
   dans le ledger avec `paper_intent_id` et `paper_trade_id`.
4. Les deltas leader `REDUCE`, `CLOSE_LONG`, `CLOSE_SHORT` sont separes des
   signaux d'entree et routent vers l'exit adapter local.
5. L'exit adapter reutilise `PaperTradingSimulator.close_paper_trade`, apres le
   commit de collecte SQLite, pour eviter les verrous de DB.
6. Les sorties paper locales sont tracees dans `DecisionLedger` avec
   `PAPER_EXIT_CLOSE`, `PAPER_EXIT_REDUCE` ou `PAPER_EXIT_NO_TRADE`,
   `exit_trigger`, `exit_reference_price`, `paper_trade_id`,
   `realized_net_pnl`.
7. Le dashboard read-only affiche maintenant le ledger avec les ids paper et les
   champs de sortie/PnL realise.
8. Un test E2E prouve:
   `copy-run open leader -> paper trade local -> second copy-run close leader ->
   closed paper trade -> realized PnL -> ledger`.
9. L'import circulaire `copy_mode -> copy_loop -> copy_run_evidence -> exit_engine`
   a ete corrige par imports paresseux dans `copy_mode/__init__.py`.
10. `ReplayEngine.replay_paper_events()` rejoue maintenant
    `OPEN_LONG/OPEN_SHORT/CLOSE_LONG/CLOSE_SHORT/REDUCE` via le meme
    `PaperTradingSimulator` et le meme exit adapter que le runtime.
11. Le replay paper produit des entrees ledger compatibles avec le runtime et
    refuse une fermeture sans position locale au lieu d'inventer un PnL.
12. `PaperReplayResult` est exporte en JSON/CSV/Markdown et le dashboard lit
    aussi les rapports `paper_replay_*.json` dans sa section Simulation.
13. Les `LEADER_REDUCE` sont maintenant traites comme reductions partielles
    proportionnelles a la baisse de taille leader quand `startPosition` et la
    taille courante sont disponibles. Le trade paper restant reste ouvert.
14. `PaperTradingSimulator.partial_close_paper_trade()` cree une ligne fermee
    pour la partie realisee et reduit la ligne ouverte existante, sans moteur
    PnL parallele.
15. `copy-report` genere maintenant un rapport periodique PnL/drawdown/frais en
    JSON/CSV/Markdown a partir des vrais `paper_trades` locaux.
16. Le dashboard read-only compare `Runtime paper DB`, dernier `copy-report` et
    dernier `paper_replay` dans une section `Runtime Paper vs Replay Paper`.
17. Le WebSocket manager expose un `qa_readiness()` borné/read-only avec
    `SourceHealth` et fallback REST explicite quand le plan n'est pas exploitable.
18. `AppConfig` lit maintenant les alias du launcher
    `HYPERSMART_SIMULATION_MIN_EDGE_BPS`,
    `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS`,
    `HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE`,
    `HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS`,
    `HYPERSMART_SIMULATION_MAX_OPEN_POSITIONS` et
    `HYPERSMART_SIMULATION_MAX_POSITION_NOTIONAL` quand les variables
    `HYPERSMART_COPY_*` / `HYPERSMART_PAPER_*` canoniques ne sont pas posees.
19. Le seuil `copy_min_liquidity_score` est configurable et transmis a
    `SignalCandidate` depuis `copy-run`; il n'est plus un `0.5` cache dans le
    moteur.
20. Le dashboard read-only affiche une section `Configuration active / seuils`
    avec les seuils qui pilotent edge/fraicheur/liquidite/degradation/paper/WS,
    sans exposer `sensitive_key_material` ni aucun secret.
21. Les docs actives cassees par le nettoyage ont ete restaurees depuis
    `docs/_archive` pour garder les tests et le plan V6 coherents.

## Fichiers principaux modifies/crees

- `hyper_smart_observer/copy_mode/__init__.py`
- `hyper_smart_observer/copy_mode/copy_loop.py`
- `hyper_smart_observer/copy_mode/copy_models.py`
- `hyper_smart_observer/copy_mode/copy_run_evidence.py`
- `hyper_smart_observer/copy_mode/reports.py`
- `hyper_smart_observer/copy_mode/signal_candidate.py`
- `hyper_smart_observer/copy_mode/copy_signal_detector.py`
- `hyper_smart_observer/app/config.py`
- `hyper_smart_observer/backtesting/replay_engine.py`
- `hyper_smart_observer/ledger/decision_ledger.py`
- `hyper_smart_observer/dashboard/exporter.py`
- `hyper_smart_observer/paper_trading/simulator.py`
- `hyper_smart_observer/paper_trading/exit_engine.py`
- `hyper_smart_observer/realtime_monitor/websocket_manager.py`
- `hyper_smart_observer/storage/repositories/paper_trades_repo.py`
- `tests/test_copy_run_follows_leader_close_paper.py`
- `tests/test_backtest_replays_fills_deltas_books.py`
- `tests/test_copy_run_evidence_wired.py`
- `tests/test_dashboard_payload_shows_decision_ledger.py`
- `tests/test_dashboard_payload_shows_paper_pnl_equity.py`
- `tests/test_exit_engine_follow_reduce_close.py`
- `tests/test_paper_engine_realized_unrealized_pnl_equity.py`
- `tests/test_ws_reconnect_snapshot_dedupe.py`
- `tests/test_hypersmart_config_threshold_explainability.py`
- `docs/audit/HYPERSMART_CURRENT_CODE_AUDIT_V6.md`
- `docs/research/HYPERSMART_GITHUB_DEEP_RESCAN_V6.md`

## Tests et commandes verifies

```powershell
python -m pytest -q tests/test_copy_run_follows_leader_close_paper.py tests/test_hypersmart_copy_network_read.py tests/test_copy_run_evidence_wired.py
# 9 passed

python -m pytest -q tests/test_backtest_replays_fills_deltas_books.py tests/test_backtest_runtime_parity_market_features_reason_codes.py tests/test_hypersmart_backtest_runtime_parity_fusion.py tests/test_runtime_replay_paper_parity.py
# 10 passed

python -m pytest -q tests/test_backtest_replays_fills_deltas_books.py tests/test_dashboard_shows_lifecycle_patterns_backtests.py tests/test_hypersmart_backtesting.py
# 11 passed

python -m pytest -q tests/test_paper_engine_realized_unrealized_pnl_equity.py tests/test_exit_engine_follow_reduce_close.py tests/test_copy_run_follows_leader_close_paper.py tests/test_copy_run_evidence_wired.py
# 16 passed

python -m pytest -q tests/test_dashboard_payload_shows_paper_pnl_equity.py tests/test_runtime_replay_paper_parity.py tests/test_backtest_replays_fills_deltas_books.py tests/test_paper_engine_realized_unrealized_pnl_equity.py tests/test_exit_engine_follow_reduce_close.py tests/test_copy_run_follows_leader_close_paper.py
# 21 passed

python -m pytest -q tests/test_ws_reconnect_snapshot_dedupe.py tests/test_hypersmart_ws_limits.py tests/test_ws_fallback_rest_polling.py tests/test_source_health_everywhere.py tests/test_hypersmart_copy_network_read.py
# 15 passed

python -m pytest -q tests/test_hypersmart_config_threshold_explainability.py tests/test_signal_candidate_market_features_gates.py tests/test_copy_run_network_read_low_liquidity_blocks_signal.py tests/test_copy_run_network_read_wide_spread_blocks_signal.py tests/test_dashboard_payload_shows_paper_pnl_equity.py
# 10 passed

python -m pytest -q tests/test_codex_master_plan_exists.py tests/test_github_fusion_docs_exist.py tests/test_github_rescan_has_keep_adapt_ban_defer.py tests/test_hypersmart_release_docs.py tests/test_scanner_fast_scan.py::test_magic_bot_research_docs_exist tests/test_no_profit_promise_docs.py
# 6 passed

python -m pytest -q tests/test_hypersmart_*.py
# 251 passed

python -m pytest -q
# 1154 passed, 12670 warnings

python -m hyper_smart_observer.app.main --runtime-check
# archive_ready=True, root_archives_zip_7z_rar=0, legacy logs DB warned

python -m hyper_smart_observer.app.main --runtime-clean-report
# non-destructive report

python -m hyper_smart_observer.app.main --archive-audit
# docs\release\HYPERSMART_ARCHIVE_AUDIT.md

python -m hyper_smart_observer.app.main --dashboard-export
# data\dashboard\hypersmart_dashboard.html

python -m hyper_smart_observer.app.main --safety-check
# Safety check: OK

python -m hyper_smart_observer.app.main --audit-safety
# all checks OK

python -m hyper_smart_observer.app.main --create-clean-archive
# C:\Users\flo\Desktop\Projet_invest_clean_20260618_175454.zip
```

## Garanties maintenues

- Aucun mainnet.
- Aucun `/exchange` operationnel.
- Aucune signature.
- Aucune cle privee.
- Aucun wallet connect.
- Aucun ordre reel.
- Aucun executor testnet actif.
- Paper/simulation locale uniquement.
- dYdX reste legacy/isole/mockable, pas runtime cible HyperSmart V6.
- Aucun fake PnL ni fake chart ajoute dans cette reprise.

## Ce qui reste a faire ensuite

Priorite exacte restante:

```text
Runtime QA longue duree
-> lancer une observation read-only bornee avec vraie shortlist Hyperliquid
-> comparer copy-run live-like, copy-report et paper_replay sur plusieurs cycles
-> enrichir timeline source-health dans le dashboard
-> ajouter tests no duplicate partial close et no duplicate replay sur event_id
-> continuer l'audit V6 jusqu'a statut DONE ligne par ligne
```

Ensuite:

- enrichir `DecisionLedger` avec une vue timeline;
- brancher plus de diagnostics source-health dans le dashboard;
- poursuivre l'audit ligne par ligne du MD V6 jusqu'a ce que chaque exigence ait
  statut `DONE`, fichier, test et commande de verification.

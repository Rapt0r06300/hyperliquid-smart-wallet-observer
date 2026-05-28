# HyperSmart Magic Bot Coverage Audit (Updated by Jules)

Status date: 2026-05-28.

Ce rapport fait la correspondance entre les exigences du Markdown et l'implémentation réelle.

| Exigence Markdown | Statut réel | Fichier(s) | Test(s) | Ce qui manque | Priorité | Action Codex recommandée |
|---|---|---|---|---|---|---|
| **Batch 1** | | | | | | |
| Smart Leaderboard + Auto-Select | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | Imports plus larges | Haute | Intégrer plus de sources de données |
| Validation adresse complète | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Maintenir la règle stricte |
| Refus adresse tronquée | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Maintenir la règle stricte |
| Consistency score | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | Historique par coin plus riche | Moyenne | Ajouter des fixtures riches |
| Max drawdown | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Rester conservateur |
| PnL concentration | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Ajuster via data réelle |
| One_big_win | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Ajuster via data réelle |
| Copyability | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | Calibration fine | Moyenne | Calibration via backtest |
| Delta detector | Delivered | `hyper_smart_observer/copy_mode/delta_detector.py` | `test_hypersmart_copy_mode.py` | Flip UNKNOWN (by design) | Haute | Modèle Flip si sécurisé |
| SignalCandidate | Delivered | `hyper_smart_observer/copy_mode/signal_candidate.py` | `test_hypersmart_copy_mode.py` | Contexte marché étendu | Haute | Ajouter plus de contexte |
| Edge_remaining_bps obligatoire | Delivered | `hyper_smart_observer/copy_mode/edge.py` | `test_hypersmart_copy_mode.py` | Aucun | Critique | Fail-closed impératif |
| No_trade_report | Delivered | `hyper_smart_observer/copy_mode/no_trade_report.py` | `test_hypersmart_copy_mode.py` | Plus de templates FR | Haute | Détails par composant |
| **Batch 2** | | | | | | |
| Leaderboard_shortlist.json | Delivered | `hyper_smart_observer/copy_mode/copy_loop.py` | `test_hypersmart_copy_mode.py` | Pas archivé par défaut | Haute | Garder dans data/ |
| Snapshots positions | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Maintenir |
| Snapshots fills | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Maintenir |
| Snapshots openOrders | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Maintenir |
| Resume cursors userFillsByTime | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_copy_mode.py` | Persistance simpliste | Moyenne | Table de reprise par wallet |
| Dedupe hash/tid/oid/time | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Garder déterministe |
| Source health | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_copy_mode.py` | Aucun | Moyenne | Vue CLI du statut |
| Collection_runs | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_copy_mode.py` | Aucun | Moyenne | Maintenir |
| Api_health | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_copy_mode.py` | Basique | Moyenne | Alerte latence |
| Stopped_reason | Delivered | `hyper_smart_observer/copy_mode/copy_loop.py` | `test_hypersmart_copy_mode.py` | Aucun | Haute | Maintenir |
| **Batch 3** | | | | | | |
| WebSocket shortlist réel | Delivered | `hyper_smart_observer/realtime_monitor/` | `test_hypersmart_ws_monitor.py` | Intégration transport | Haute | Tests de bout en bout |
| Max 10 users uniques | Delivered | `hyper_smart_observer/realtime_monitor/` | `test_hypersmart_ws_limits.py` | Aucun | Critique | Maintenir strict |
| Duration limitée | Delivered | `hyper_smart_observer/realtime_monitor/` | `test_hypersmart_ws_monitor.py` | Aucun | Critique | Maintenir strict |
| Fallback polling | Delivered | `hyper_smart_observer/copy_mode/copy_loop.py` | `test_hypersmart_copy_mode.py` | Transition fluide WS/Poll | Moyenne | Améliorer le switch |
| Heartbeat | Delivered | `hyper_smart_observer/realtime_monitor/` | `test_hypersmart_ws_monitor.py` | Aucun | Haute | Maintenir |
| Reconnect / Backoff | Delivered | `hyper_smart_observer/realtime_monitor/` | `test_hypersmart_ws_monitor.py` | Aucun | Haute | Maintenir |
| No infinite monitor | Delivered | `hyper_smart_observer/realtime_monitor/` | `test_hypersmart_ws_monitor.py` | Aucun | Critique | Maintenir strict |
| Déduplication snapshot isSnapshot | Delivered | `hyper_smart_observer/copy_mode/snapshot_engine.py` | `test_hypersmart_ws_dedupe.py` | Aucun | Haute | Maintenir |
| **Batch 4** | | | | | | |
| Replay/backtest deltas | Partial | `hyper_smart_observer/backtesting/` | `test_hypersmart_backtesting.py` | Scénarios directs | Haute | Étendre le moteur de replay |
| Délai 5m / 60s / WS | Partial | `hyper_smart_observer/backtesting/` | `test_hypersmart_backtesting.py` | Sélecteur de scénario CLI | Moyenne | Ajouter des flags CLI |
| Missed/partial fills | Partial | `hyper_smart_observer/backtesting/` | `test_hypersmart_backtesting.py` | Manque de fixtures L2 | Moyenne | Ajouter fixtures L2/Slippage |
| Fees / Spread / Slippage | Delivered | `hyper_smart_observer/paper_trading/` | `test_hypersmart_paper_fees.py` | Aucun | Haute | Maintenir |
| Latency | Delivered | `hyper_smart_observer/paper_trading/` | `test_hypersmart_paper_latency.py` | Aucun | Haute | Maintenir |
| Equity curve | Partial | `hyper_smart_observer/dashboard/` | `test_hypersmart_dashboard_renderer.py` | Rendu temps réel stable | Haute | Améliorer Metagraphe |
| No_trade_report rétrospectif | Partial | `hyper_smart_observer/copy_mode/no_trade_report.py` | `test_no_trade_analytics.py` | Intégration backtest | Moyenne | Relier au replay |
| **Batch 5** | | | | | | |
| Dashboard copy status | Delivered | `hyper_smart_observer/dashboard/` | `test_hypersmart_dashboard_readonly.py` | Exports CSV riches | Haute | Enrichir les exports |
| Paper mock USDC portfolio | Delivered | `hyper_smart_observer/paper_trading/` | `test_hypersmart_paper_portfolio.py` | Aucun | Haute | Rester local only |
| Export CSV/HTML | Delivered | `hyper_smart_observer/dashboard/` | `test_hypersmart_dashboard_renderer.py` | Plus de colonnes | Haute | Ajouter colonnes techniques |
| **Batch 6** | | | | | | |
| Seulement verrouillé | Delivered | `hyper_smart_observer/execution/` | `test_no_mainnet_execution.py` | Aucun | Critique | Ne jamais déverrouiller |
| Aucun executor actif | Delivered | `hyper_smart_observer/execution/` | `test_no_mainnet_execution.py` | Aucun | Critique | Vérifier via audit |
| Aucune signature / exchange | Delivered | `hyper_smart_observer/audit/` | `test_hypersmart_audit_safety.py` | Aucun | Critique | Vérifier via audit |

# HyperSmart V12 - Implementation Status

Mise a jour: 2026-06-21

Source de verite: `docs/HYPERSMART_FUSION_ROADMAP_V12.md`.

Decision d'architecture: le runtime principal est `src/hl_observer/`. Le package
`hyper_smart_observer/` reste conserve pour compatibilite historique, modules de
recherche et CLI legacy. Les nouveaux blocs V12 sont ajoutes comme petits
modules importables, sans edition massive de `src/hl_observer/cli.py` ni
`src/hl_observer/ui/routes.py`.

Doctrine maintenue: Hyperliquid par defaut, simulation paper locale uniquement,
donnees reelles ou etat vide honnete, aucun `/exchange`, aucun ordre reel,
aucune cle privee, aucune signature, aucun wallet connect, aucun faux PnL,
aucune fausse position, aucun faux graphe.

## Statut Global Par Bloc

| Bloc V12 | Statut reel | Fichiers principaux | Tests | Prochaine action |
|---|---|---|---|---|
| SourceRegistry / FetchProvenance | DONE | `src/hl_observer/sources/registry.py`, `src/hl_observer/sources/models.py`, `src/hl_observer/sources/collection_recorder.py` | `tests/test_v12_source_registry.py`, `tests/test_v12_collection_recorder.py` | Persister plus largement les source-health dans le dashboard. |
| RunContext | DONE | `src/hl_observer/storage/run_context.py` | RawStore + backtest tests | Exposer le contexte dans chaque rapport runtime/backtest. |
| RawStore / dedupe | DONE | `src/hl_observer/storage/raw_store.py` | `tests/test_v12_raw_store.py` | Ajouter backend SQLAlchemy complet si besoin; le mini-store V12 existe deja. |
| SQLite V12 artifacts | DONE (slice) | `src/hl_observer/storage/v12_sqlite_store.py` | `tests/test_v12_sqlite_store.py` | Brancher le moteur live pour persister automatiquement scores/clusters/edge/evidence. |
| ProxyPool / WeightBudgeter / backoff / circuit breaker | PARTIAL+ | `src/hl_observer/collection/proxy_pool.py`, `weight_budgeter.py`, `backoff.py`, `circuit_breaker.py` | `tests/test_v9_proxy_pool_safe_sharding.py`, `tests/test_hypersmart_v9_collection_budget.py`, `tests/test_v9_collection_resilience_and_html.py` | Relier les budgets aux runs de collecte live et au panneau source/proxy health. |
| Public scraping read-only + cache/provenance | DONE (slice) | `src/hl_observer/collection/html_scraper.py`, `src/hl_observer/collection/public_fetcher.py` | `tests/test_v12_public_fetcher.py` | Ajouter parsers publics specialises Hyperliquid Explorer sans fake data. |
| Hyperliquid `/info` read-only pagination | DONE (slice) | `src/hl_observer/hyperliquid/info_readonly.py`, `rate_weights.py` | `tests/test_v12_info_readonly_pagination.py` | Brancher toutes les routes `/info` attendues dans un client runtime unique. |
| WebSocket supervisor read-only | DONE (slice), PARTIAL runtime | `src/hl_observer/realtime_monitor/ws_supervisor.py` | `tests/test_v12_ws_supervisor_provenance.py`, tests WS existants | Ajouter recovery gaps/rest reconcile et metrics dashboard. |
| NormalizedFill / NormalizedPosition | DONE (slice) | `src/hl_observer/normalization/fills.py`, `positions.py` | `tests/test_v12_normalization_lifecycle_leader_delta.py` | Cablage live generalise a tous les fetchers. |
| PositionLifecycle OPEN/ADD/INCREASE/REDUCE/CLOSE/FLIP/LIQUIDATION/UNKNOWN | DONE (slice) | `src/hl_observer/position_lifecycle/reconstructor.py` | `tests/test_v12_normalization_lifecycle_leader_delta.py`, `tests/test_v12_position_lifecycle.py` | Ajouter episodes persistants, holding time et closedPnl consolide. |
| LeaderDelta | DONE (slice) | `src/hl_observer/signals/leader_delta.py` | `tests/test_v12_normalization_lifecycle_leader_delta.py` | Brancher aux flux live et au DecisionLedger. |
| V12 decision pipeline | DONE (local slice), PARTIAL runtime | `src/hl_observer/pipeline/v12_decision_pipeline.py` | `tests/test_v12_decision_pipeline.py` | Brancher le poller/live scanner sur cette pipeline au lieu de chemins disperses. |
| MarketFeatures 70+ colonnes + feature_hash | DONE (schema slice), PARTIAL full features | `src/hl_observer/features/scan_features_schema.py`, `scan_features.py` | `tests/test_v12_scan_features_schema.py` | Calculer plus de features l2/trades/candles en live selon disponibilite reelle. |
| WalletScoreV2 / copyability | DONE (slice), PARTIAL integration | `src/hl_observer/scoring/wallet_score_v2.py` | `tests/test_v12_wallet_score_cluster.py` | Alimenter depuis fills normalises et persister via V12SQLiteStore. |
| ClusterDetector multi-wallet frais | DONE (slice), PARTIAL integration | `src/hl_observer/signals/cluster_detector.py` | `tests/test_v12_wallet_score_cluster.py` | Lier clusters frais a OpportunityRanker puis RiskEngine. |
| PatternDetector | DONE (slice), PARTIAL integration | `src/hl_observer/patterns/pattern_detector.py` | `tests/test_v12_pattern_detector.py` | Afficher patterns dans wallet detail/dashboard et persister. |
| EdgeNet V12 | DONE (slice), PARTIAL integration | `src/hl_observer/edge/edge_net_v12.py` | `tests/test_v12_edge_net_estimator.py` | Remplacer progressivement les calculs disperses par ce contrat mesurable. |
| RiskEngine deny-by-default | PARTIAL | `src/hl_observer/risk/*` | risk tests existants | Unifier toutes les entrees paper via un ApprovedPaperIntent. |
| NO_TRADE taxonomy | DONE (slice), PARTIAL persistence | `src/hl_observer/signals/no_trade_taxonomy.py` | `tests/test_v12_no_trade_taxonomy.py`, `tests/test_v12_no_trade_explorer.py` | Stocker les codes canoniques dans chaque evidence/log. |
| DecisionLedger / EvidenceChain | DONE (slice), PARTIAL persistence | `src/hl_observer/evidence/decision_ledger.py` | `tests/test_v12_paper_engine_evidence.py` | Unifier ledger runtime et legacy, ajouter source refs complets. |
| PaperEngine local simulation | DONE (slice), PARTIAL full depth | `src/hl_observer/paper_trading/paper_engine.py`, `exec_model.py` | `tests/test_v12_paper_engine_evidence.py` | Ajouter queue/funding/liquidation plus riches et persistance automatique. |
| Exit handling reduce/close | DONE (important fix), PARTIAL exit strategy | `src/hl_observer/paper_trading/paper_engine.py` | `tests/test_v12_paper_engine_evidence.py` | Ajouter exit_engine dedie: trailing, time stop, max MAE, TP/SL unifies. |
| Backtest / Replay no-lookahead | DONE (slice), PARTIAL full runner | `src/hl_observer/backtesting/experiment.py` | `tests/test_v12_backtest_experiment.py` | Ajouter ledger/book/trade replay et walk-forward. |
| Dashboard V12 status | DONE (status slice), PARTIAL full dashboard | `src/hl_observer/ui/v12_status_provider.py`, `status_routes.py` | `tests/test_ui_simulation_status_fast.py` | Ajouter panneaux complets: sources, clusters, edge, evidence, backtests. |
| Agent tools local-only | DONE (manifest slice), PARTIAL implementation | `src/hl_observer/agent_tools/manifest.py` | `tests/test_v12_agent_tools_manifest.py` | Implementer les handlers locaux bornes pour chaque tool. |
| QA safety / no fake data | PARTIAL+ | safety tests, fake-data scanner | `tests/test_v12_fake_data_scanner.py`, safety tests | Etendre audit aux nouveaux modules et dashboard genere. |

## Capacites Ajoutees Dans Cette Session

- Alignement launcher/runtime sur des seuils explicites de simulation.
- Normalisation Hyperliquid fills/positions.
- Reconstruction lifecycle OPEN/ADD/INCREASE/REDUCE/CLOSE/FLIP/LIQUIDATION/UNKNOWN.
- LeaderDelta avec entree vs sortie et `safe_for_paper_candidate`.
- PaperEngine local V12 avec open/reduce/close, PnL, equity et drawdown.
- Correction importante: les gates d'entree ne bloquent plus une fermeture/reduction paper locale quand une position existe.
- EvidenceChain deterministe depuis resultats PaperEngine.
- Feature schema V12 70+ colonnes avec `feature_hash`.
- WS supervisor provenance: les messages WS sont associes a SourceRegistry/RawStore.
- Pagination `/info` userFillsByTime bornee: page limit, max pages, max fills, stopped_reason.
- WalletScoreV2: history days, closed_pnl points, winrate, PF, drawdown, concentration, one-big-win, per-coin stability, copyability.
- ClusterDetector: meme coin + meme sens + fenetre 4s, refus single-wallet/stale/low-confidence.
- EdgeNet V12: refus explicite si mid/prix leader/frais/liquidite manquent, couts visibles, net edge.
- Mini-store SQLite V12 idempotent pour wallet scores, clusters, edge estimates, evidence.
- PublicFetcher read-only avec cache, provenance, raw store et refus login/captcha/non-public URL.
- PatternDetector research-only: insufficient data, one-big-win, coin specialist, cuts losses, lets winners run.
- Agent tools manifest `src/hl_observer` avec read + local_write local-only, sans action externe.
- Pipeline V12 locale: raw Hyperliquid fills -> SourceMeta -> normalisation -> lifecycle -> LeaderDelta -> clusters -> EdgeNetV12 -> RiskEngine/PaperEngine -> EvidenceChain -> V12SQLiteStore.
- Test end-to-end sans reseau: ouverture paper, fermeture leader suivie, PnL/equity/evidence persistants; refus propre si mid marche absent.
- Status/dashboard V12 lit un chemin `v12_sqlite_path` annonce par le moteur et expose les compteurs wallet_scores, clusters, edge estimates et evidences sans lignes inventees.

## Tests Lances Et Resultats

- `python -m pytest -q tests/test_v12_*.py`
  - Resultat: 142 passed.
- `python -m pytest -q tests/test_v12_decision_pipeline.py`
  - Resultat: 2 passed.
- `python -m pytest -q tests/test_ui_simulation_status_fast.py tests/test_v12_decision_pipeline.py tests/test_v12_sqlite_store.py`
  - Resultat: 23 passed.
- Tests cibles deja lances durant la session:
  - launcher/simulation thresholds: 36 passed.
  - normalization/lifecycle/leader delta: 28 passed.
  - paper engine/evidence/backtest/no-exchange subset: 16 passed.
  - wallet score/cluster/ranking: 33 passed.
  - no-trade taxonomy/explorer/cluster codes: 34 passed.
  - edge/risk subset: 21 passed.
  - source/raw/sqlite/ws foundation: 39 passed.
  - collection/proxy/public fetcher: 34 passed.
  - agent/safety subset: 10 passed.

## DONE / PARTIAL / BLOCKED / DEFER

DONE:
- SourceRegistry in-memory.
- RawStore in-memory.
- V12SQLiteStore additive.
- Public fetcher with cache/provenance.
- NormalizedFill/NormalizedPosition slice V12.
- PositionLifecycle slice V12 avec FLIP et LIQUIDATION.
- LeaderDelta slice V12.
- ClusterDetector slice V12.
- WalletScoreV2 slice V12.
- EdgeNet V12 estimator.
- NO_TRADE taxonomy enrichie cluster.
- PaperEngine V12 slice et EvidenceChain.
- V12 decision pipeline locale end-to-end.
- Backtest experiment no-lookahead slice.
- Agent tools manifest local-only.
- V12 targeted tests all green.

PARTIAL:
- Integration runtime complete REST/WS -> V12 decision pipeline -> dashboard.
- Dashboard complet V12 multi-pages.
- Full market features from allMids/l2Book/candles/trades en production.
- Strategy registry et optimization/walk-forward complets.
- Audit safety context-aware complet sur tous les nouveaux modules.

BLOCKED:
- Rien n'est bloque par une action externe. Les donnees live restent soumises aux limites publiques Hyperliquid et doivent rester bornees, traçables et read-only.

DEFER:
- Toute execution testnet/mainnet reelle.
- Toute signature reelle.
- Tout wallet connect.
- Toute integration runtime Polymarket/Kalshi/dYdX.
- Toute donnee de demonstration/fake.
- Toute promesse de gain.

## NEXT CODEX OBJECTIVE

Continuer V12 par le branchement runtime/dashboard:

1. Brancher le scanner/poller Hyperliquid existant sur `run_v12_decision_pipeline()` pour eviter les chemins de decision disperses.
2. Faire ecrire au moteur runtime `metrics.v12_sqlite_path` dans `hypersmart_engine_status.json`.
3. Ajouter dashboard sections read-only pour clusters, edge estimates, wallet scores, no-trade reasons et evidence hashes.
4. Ajouter export periodique des evidences/no-trades dans `logs/logs a envoyer`.
5. Lancer ensuite `python -m pytest -q`, `--safety-check`, `--audit-safety`.

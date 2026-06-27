# HYPERSMART V12 — NEXT STEPS (mis à jour 2026-06-22)

> La **logique pure** V12 (A→U) est implémentée et testée (**269 tests verts en sandbox**).
> Le câblage runtime est posé en **insertions gardées** (try/except → repli, jamais de casse moteur),
> en **mode shadow** pour la décision (le verdict du gate unifié est exposé mais ne remplace pas encore
> la décision réelle). Règles constantes : additif, paper-only, read-only, deny-by-default, 0 fake,
> Hyperliquid défaut, dYdX dormant, bypass conservé, aucune action argent-réel.

## Fait (roadmap #97→#119)
- **Fondation/Collecte** : SourceRegistry, RawStore (+ SQLite persistant), CollectionRecorder (REST+WS, recorder partagé), reconcile_quotes→SOURCE_CONFLICT.
- **Lifecycle/Décision** : classify_lifecycle + LIQUIDATION, lifecycle_gate, NO_TRADE taxonomy §17 (57 codes) + Explorer + Decision Funnel, copy_decision (gate unifié) câblé en SHADOW dans routes.py.
- **Simulation/Backtest** : fill_outcomes (partial/missed/funding), exit_evidence (TP/SL/trailing/liquidation), no_lookahead_guard, StrategyRegistry + stratégies de référence (chaîne strategy→risk→approved).
- **Produit/Agent/QA** : panneaux Source Health + NO_TRADE Explorer (routes.py), agent read-only inspectors + manifeste MCP read-only, release_readiness go/no-go, clean_archive.
- **Robustesse** : 2 fixes portabilité Python 3.10 (StrEnum), badge WS honnête, leviers fills frais (fenêtre 45 s + scoring découverte activité-forward).

## Reste (promotion live, à faire/vérifier sur Windows)
1. **Promouvoir le gate unifié de SHADOW → autoritatif** : remplacer `decision_reason`/`score.accepted` par le verdict `evaluate_copy_candidate` quand tu es confiant (le shadow tourne déjà sur données live).
2. **Activer le recorder partagé** : confirmer que l'orchestrateur lit `get_shared_recorder()` pour afficher la vraie santé des sources, et brancher `reconcile_quotes(REST allMids vs WS)`.
3. **Rendu UI** des panneaux Source Health / NO_TRADE Explorer / Decision Funnel dans `simulation_v2.html` (le backend renvoie déjà les payloads).
4. **Câbler StrategyRegistry** dans la boucle (PaperIntent → RiskEngine → ApprovedPaperIntent → PaperEngine) pour le multi-stratégies au-delà du copy-follow.
5. **Charts** Paper Portfolio (equity curve / drawdown) — PnL/equity/positions déjà exposés.

## Vérification
- Sandbox : `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q tests/test_v12_*.py` → **269 verts**.
- **Windows (à lancer par toi)** : `PYTHONPATH=src python -m pytest -q tests/` — confirme aussi les 3 tests d'intégration recorder (`test_v12_collection_recorder::test_rest_client_*`) que le sandbox ne peut pas exécuter (lecture corrompue de `rest_info_client.py` ; le fichier réel est correct).

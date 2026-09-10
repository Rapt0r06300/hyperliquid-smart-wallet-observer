# H—T-36 — Mapping P0 V5 lot 01

Baseline auditée : `52e5ddde10ae8211a5b2583caa60681632121545` (`main`).
Dernier HEAD audité pour ce checkpoint : `54ebc9778bfcb9ccb2a99c916be8e322e74b95f8` (`main`).
Source de scope : `HYPERSMART_MASTER_ROADMAP_CODING_AGENTS_V5_2026-08-30.md` + améliorations 776+ validées ensuite.
Ce document est un checkpoint de preuve ; il ne remplace ni `SECURITY.md`, ni `docs/HYPERSMART_CONSTITUTION.md`, ni les contrats machine du HEAD exact.

## Classification

| Exigence | État courant | Preuve vérifiée | Reste exact |
|---|---|---|---|
| P0-001 — rebaseline exacte | CORRIGÉ / PARTIEL | HEAD exact relu ; `docs/CURRENT_STATE.md` distingue la roadmap technique V5/776+ de `pre-run-775`; `main` reste l’unique branche persistante. | Compléter le receipt final H—T-36 avec delta explicite vs baseline historique V5 `81069e7f0af0690c5dfc268cb95bc89d2fe76a57` et états CI/workflows du SHA final. |
| P0-050 — Constitution unique et précédence | CORRIGÉ | `docs/HYPERSMART_CONSTITUTION.md`; `src/hl_observer/ops/document_authority.py`; `tests/test_document_authority.py`; `tools/check_document_authority.py`. | Vérifier les gates CI au SHA final et conserver la hiérarchie sans régression. |
| P0-110 — inventaire flags/entrypoints | CORRIGÉ / VALIDATION CI EN COURS | `src/hl_observer/ops/scope_flag_inventory.py` expose la taxonomie V5 et un audit fail-closed ; `tests/test_scope_flag_inventory.py` vérifie exhaustivité, defaults sûrs et absence d’autorité de scope par l’environnement. Le commit E1 `91ee2af2e289a490424475f245436938f3548205` a révélé en CI 5 seuils/budgets non enregistrés ; le HEAD courant les classe explicitement sans leur donner d’autorité de scope. | Attendre le verdict frais du shard contenant `tests/test_scope_flag_inventory.py` au HEAD courant ; ne fermer qu’après GREEN exact-SHA. |
| P0-115 — audit de tous les `.cmd` | DÉJÀ-IMPLÉMENTÉ / À REVALIDER | `src/hl_observer/ops/entrypoint_topology.py` inventorie les lanceurs racine, impose un entrypoint officiel unique par rôle, Python portable, verrous mainnet/testnet et absence de duplication runtime/recherche ; `tests/test_entrypoint_topology.py` teste le dépôt courant et les dérives fail-closed. | Obtenir un résultat CI frais au SHA final et conserver l’inventaire exhaustif si un `.cmd` est ajouté/supprimé. |
| P0-120 — Empirical Memory Registry | À CORRIGER | `src/hl_observer/research/lois_mesurees.py` est la source unique de `docs/LOIS_MESUREES.md`, mais le modèle `Loi` ne porte que clé/titre/verdict/chiffre/date/condition/mots-clés/où-vérifier. | Ajouter provenance structurée, hash de preuve, freshness/revalidation explicites et fail-closed pour une loi non revalidable/stale ; `LOIS_MESUREES` ne doit jamais devenir autorité d’ACTIVE_SCOPE. |

## Incident P0-110 et cause racine

- Le run CI du commit `91ee2af2e289a490424475f245436938f3548205` a échoué sur 2 tests de `tests/test_scope_flag_inventory.py` : 455 autres tests du shard étaient verts.
- Cause racine : `.env.example` contenait cinq paramètres à noms scope-like (`HYPERSMART_COPY_MIN_EDGE_REQUIRED_BPS`, `HYPERSMART_PAPER_MAX_DRAWDOWN_ALLOWED`, `HYPERSMART_V26_UNSTUCK_BUDGET_USD`, `HYPERSMART_V26_HALT_AMBER_LOSS_USD`, `HYPERSMART_V26_HALT_RED_LOSS_USD`) absents du registre restauré.
- Le HEAD `54ebc9778bfcb9ccb2a99c916be8e322e74b95f8` les contient dans `SCOPE_FLAG_RECORDS` comme seuils/budgets explicitement non autoritaires pour le scope. Aucun correctif concurrent n'est dupliqué par E1.

## Invariants conservés

- Roadmap technique : aucun seuil `+4 USD`, `3×4 USD` ou PnL positif n’est un critère de Done.
- Paper/read-only, 0 €, aucune exécution réelle mainnet/testnet.
- Aucun test, coverage ou gate ne peut être affaibli pour fermer le lot.
- Les éléments historiques restent conservés et classés ; ils ne sont jamais réactivés implicitement.

## Ordre de fermeture recommandé

1. Revalider P0-110/P0-115 sur un SHA frais et conserver l’inventaire exhaustif flags + entrypoints.
2. P0-120 : étendre le registre empirique avec provenance/hash/freshness/revalidation en TDD.
3. P0-001 : produire le Completion Receipt exact-SHA final avec delta baseline et CI.
4. Rejouer le gate d’autorité documentaire et la régression pertinente avant passage Testing/Review.

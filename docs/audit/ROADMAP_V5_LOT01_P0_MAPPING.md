# H—T-36 — Mapping P0 V5 lot 01

Baseline historique V5 : `81069e7f0af0690c5dfc268cb95bc89d2fe76a57`.
Baseline de ce lot : `52e5ddde10ae8211a5b2583caa60681632121545` (`main`).
Dernier HEAD audité avant ce checkpoint : `e1ebcc5305e11ae03e70673f1833bed21b9f055f` (`main`).
Source de scope : `HYPERSMART_MASTER_ROADMAP_CODING_AGENTS_V5_2026-08-30.md` + améliorations 776+ validées ensuite.
Ce document est un checkpoint de preuve ; il ne remplace ni `SECURITY.md`, ni `docs/HYPERSMART_CONSTITUTION.md`, ni les contrats machine du HEAD exact.

## Classification

| Exigence | État courant | Preuve vérifiée | Reste exact |
|---|---|---|---|
| P0-001 — rebaseline exacte | CORRIGÉ / PARTIEL | HEAD exact relu ; `docs/CURRENT_STATE.md` distingue la roadmap technique V5/776+ de `pre-run-775`; `main` reste l’unique branche persistante. Le delta depuis la baseline historique V5 est explicitement ancré ci-dessus. | Produire le Completion Receipt final H—T-36 au SHA de fermeture avec états CI/workflows exacts. |
| P0-050 — Constitution unique et précédence | CORRIGÉ | `docs/HYPERSMART_CONSTITUTION.md`; `src/hl_observer/ops/document_authority.py`; `tests/test_document_authority.py`; `tools/check_document_authority.py`. Au SHA `e1ebcc53`, `hypersmart/security-quality` est GREEN, y compris le job Gouvernance du dépôt. | Conserver la hiérarchie sans régression jusqu’au SHA final. |
| P0-110 — inventaire flags/entrypoints | CORRIGÉ / À REVALIDER CIBLÉ | `src/hl_observer/ops/scope_flag_inventory.py` expose la taxonomie V5 ACTIVE/LEGACY_COMPAT/DEAD/HISTORICAL_COMMENT_ONLY/AMBIGUOUS et un audit fail-closed. Les cinq seuils/budgets révélés par CI sont désormais classés explicitement comme non autoritaires. | Obtenir une preuve fraîche du test ciblé `tests/test_scope_flag_inventory.py` sur le SHA final ; ne pas assimiler le GREEN sécurité global à ce test ciblé. |
| P0-115 — audit de tous les `.cmd` | DÉJÀ-IMPLÉMENTÉ / À REVALIDER CIBLÉ | `src/hl_observer/ops/entrypoint_topology.py` inventorie les lanceurs racine, impose un entrypoint officiel unique par rôle, Python portable, verrous mainnet/testnet et absence de duplication runtime/recherche ; `tests/test_entrypoint_topology.py` couvre les dérives fail-closed. | Obtenir une preuve fraîche du test ciblé au SHA final et conserver l’inventaire exhaustif si un `.cmd` est ajouté/supprimé. |
| P0-120 — Empirical Memory Registry | CORRIGÉ / À REVALIDER CIBLÉ | Historique : `empirical_memory.py` conserve preuves URI/SHA-256/freshness et `EMPIRICAL_MEMORY_IS_ACTIVE_SCOPE_AUTHORITY = False`. Extension V5 au commit `9b850a72fcfafba04178ec1b9a8caeb08c391575` : `empirical_law_registry.py` expose une vue machine-readable fail-closed avec law_id, hypothesis_family, verdict, measured_value/measured_at, dataset/hash, experiment/git_sha/cost_model, sources/hash, evidence_quality, last_verified/retest_after, invalidated_if, scope_status, conservation des REFUTE et gate de réouverture. | Revalider `tests/test_empirical_law_registry.py` sur le SHA final. Le rouge security-quality de `9b850a72` venait d’une annulation/failure d’upload-artifact pendant l’installation, pas d’une preuve de défaut fonctionnel P0-120 ; au HEAD `e1ebcc53`, security-quality est GREEN après correction CI. |

## Incident P0-110 — cause racine conservée

- Le run CI du commit `91ee2af2e289a490424475f245436938f3548205` a échoué sur 2 tests de `tests/test_scope_flag_inventory.py` ; 455 autres tests du shard étaient verts.
- Cause racine : `.env.example` contenait cinq paramètres à noms scope-like absents du registre restauré.
- Le HEAD les contient désormais dans `SCOPE_FLAG_RECORDS` comme seuils/budgets explicitement non autoritaires pour le scope. Aucun correctif concurrent n’est dupliqué.

## Validation CI fraîche disponible

- SHA audité : `e1ebcc5305e11ae03e70673f1833bed21b9f055f`.
- `hypersmart/security-quality` : GREEN ; gouvernance, supply-chain et analyse statique sont vertes.
- `hypersmart/coverage-parallel-probe` : RED. Cette dette n’est pas masquée et n’est pas utilisée pour prétendre que les tests ciblés P0-110/P0-115/P0-120 sont verts.
- Aucun gate/coverage n’a été abaissé dans ce lot.

## Invariants conservés

- Roadmap technique : aucun seuil `+4 USD`, `3×4 USD` ou PnL positif n’est un critère de Done.
- Paper/read-only, 0 €, aucune exécution réelle mainnet/testnet.
- Aucun test, coverage ou gate ne peut être affaibli pour fermer le lot.
- Les éléments historiques restent conservés et classés ; ils ne sont jamais réactivés implicitement.

## Ordre de fermeture

1. Revalider les tests ciblés P0-110/P0-115/P0-120 sur un SHA frais.
2. Produire le Completion Receipt P0-001 exact-SHA avec delta baseline + CI.
3. Rejouer le gate d’autorité documentaire et la régression pertinente avant Testing/Review.

# H—T-36 — Mapping P0 V5 lot 01

Baseline auditée : `52e5ddde10ae8211a5b2583caa60681632121545` (`main`).
Source de scope : `HYPERSMART_MASTER_ROADMAP_CODING_AGENTS_V5_2026-08-30.md` + améliorations 776+ validées ensuite.
Ce document est un checkpoint de preuve ; il ne remplace ni `SECURITY.md`, ni `docs/HYPERSMART_CONSTITUTION.md`, ni les contrats machine du HEAD exact.

## Classification

| Exigence | État au baseline | Preuve vérifiée | Reste exact |
|---|---|---|---|
| P0-001 — rebaseline exacte | CORRIGÉ / PARTIEL | HEAD exact relu ; `docs/CURRENT_STATE.md` distingue la roadmap technique V5/776+ de `pre-run-775`; `main` reste l’unique branche persistante. | Compléter le receipt final H—T-36 avec delta explicite vs baseline historique V5 `81069e7f0af0690c5dfc268cb95bc89d2fe76a57` et états CI/workflows du SHA final. |
| P0-050 — Constitution unique et précédence | CORRIGÉ | `docs/HYPERSMART_CONSTITUTION.md`; `src/hl_observer/ops/document_authority.py`; `tests/test_document_authority.py`; `tools/check_document_authority.py`. | Vérifier les gates CI au SHA final et conserver la hiérarchie sans régression. |
| P0-110 — inventaire flags/entrypoints | BLOCKED / MANQUANT | Aucun registre utilisant la taxonomie V5 `ACTIVE`, `LEGACY_COMPAT`, `DEAD`, `HISTORICAL_COMMENT_ONLY`, `AMBIGUOUS` n’a été trouvé au baseline ; plusieurs lanceurs `.cmd` existent encore à la racine. | Produire un inventaire machine-readable exhaustif des flags/entrypoints et classifier chacun ; aucun testnet/scope historique ne doit redevenir actif. |
| P0-115 — audit de tous les `.cmd` | BLOCKED / MANQUANT | Lanceurs racine présents, notamment `ANALYSER_BACKTESTS_REPLAYS.cmd`, `ANALYSER_DONNEES_HYPERSMART.cmd`, `ANALYSE_HISTORIQUE_COMPLETE.cmd`; aucune preuve d’un inventaire canonique complet n’a été trouvée au baseline. | Retester/classifier tous les `.cmd`, imposer un rôle opérationnel = un entrypoint canonique, vérifier Python portable/no-execution et absence de collecteurs dupliqués. |
| P0-120 — Empirical Memory Registry | À CORRIGER | `src/hl_observer/research/lois_mesurees.py` est la source unique de `docs/LOIS_MESUREES.md`, mais le modèle `Loi` ne porte que clé/titre/verdict/chiffre/date/condition/mots-clés/où-vérifier. | Ajouter provenance structurée, hash de preuve, freshness/revalidation explicites et fail-closed pour une loi non revalidable/stale ; `LOIS_MESUREES` ne doit jamais devenir autorité d’ACTIVE_SCOPE. |

## Invariants conservés

- Roadmap technique : aucun seuil `+4 USD`, `3×4 USD` ou PnL positif n’est un critère de Done.
- Paper/read-only, 0 €, aucune exécution réelle mainnet/testnet.
- Aucun test, coverage ou gate ne peut être affaibli pour fermer le lot.
- Les éléments historiques restent conservés et classés ; ils ne sont jamais réactivés implicitement.

## Ordre de fermeture recommandé

1. P0-110/P0-115 : construire l’inventaire exhaustif flags + entrypoints et les tests de cohérence.
2. P0-120 : étendre le registre empirique avec provenance/hash/freshness/revalidation en TDD.
3. P0-001 : produire le Completion Receipt exact-SHA final avec delta baseline et CI.
4. Rejouer le gate d’autorité documentaire et la régression pertinente avant passage Testing/Review.

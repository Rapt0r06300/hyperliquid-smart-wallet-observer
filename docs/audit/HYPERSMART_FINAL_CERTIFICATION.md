# HyperSmart — certification finale

Date : 2026-08-12

Ce document fige le candidat de clôture du chantier de durcissement HyperSmart. Il est volontairement descriptif : le verdict CI final doit provenir des GitHub Actions du commit qui ajoute ce fichier, jamais d'une déclaration manuelle.

## Candidat fonctionnel immédiatement précédent

- SHA : `c128f20183985dfd537aa2d6b6e5758c57c05dee`
- Objet : aligner les régressions de tests avec les invariants runtime durcis.

## Invariants de clôture

- HyperSmart reste en paper/read-only.
- `HL_ENABLE_MAINNET_EXECUTION=0`.
- `HL_ENABLE_TESTNET_EXECUTION=0`.
- Aucun ordre réel, aucune signature et aucune clé privée ne sont requis par le runtime officiel.
- Le lanceur officiel utilise un Python portable appartenant au checkout courant.
- Les détections/arrêts de processus HyperSmart sont bornés au checkout courant.
- Le legacy Cross-Venue v1 `HYPERSMART_ARB_DISLOCATION_PAPER` reste désactivé dans le lanceur ; la voie actuelle reste autoritaire.
- Une position Cross-Venue sans ses deux jambes d'entrée réconciliables ne publie pas un faux realized : elle reste ouverte et marquée `UNLIQUIDATABLE_DATA_MISSING`.
- Une sortie Cross-Venue réconciliable comptabilise les coûts aller-retour des deux jambes.
- Le fallback taker Hyperliquid utilisé par le projet est 4.5 bps.
- Le ledger EXP porte l'identité de session/lane/cohort et sépare le PnL session du lifetime.
- L'exposition Cross-Venue est budgétée en exposition brute deux jambes.
- L'état paper Lead-Lag événementiel est restaurable après redémarrage BBO.
- Les installations critiques de la CI principale sont fail-closed.
- Le GET de statut reste une voie d'observation ; les mutations économiques appartiennent au writer runtime dédié selon les tests de non-régression du dépôt.

## Régressions corrigées juste avant certification

1. Les tests du lanceur vérifient désormais `& $PythonExe -m hl_observer ...` au lieu de réimposer un `python` global.
2. Le test legacy arbitrage vérifie `HYPERSMART_ARB_DISLOCATION_PAPER=0` au lieu de réactiver la v1.
3. Le coût stress deux jambes corrige l'arithmétique : 36 bps × 100 USD × 2 jambes = 0.72 USD.
4. Le test DATA_MISSING sans jambes d'entrée exige désormais l'absence de `CLOSE` fabriqué et le statut `UNLIQUIDATABLE_DATA_MISSING`.

## Critère de DONE

Ce chantier n'est certifié DONE que si les workflows GitHub obligatoires du SHA de ce document sont terminés avec succès, notamment :

- `hypersmart-ci` ;
- `hyperlab-ci` ;
- `labo-continu-ci` ;
- `alpha-factory` ;
- `portable-release-windows`.

Tout rouge doit être analysé depuis son log exact et corrigé avant clôture. Aucun post-commit de documentation ne doit être ajouté après la certification, afin de conserver le même SHA entre le code certifié et le verdict final.

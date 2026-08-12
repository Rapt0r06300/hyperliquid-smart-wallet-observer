# HyperSmart — certification finale

Date : 2026-08-12

Ce document fige le candidat de clôture du chantier de durcissement HyperSmart. Il est volontairement descriptif : le verdict CI final doit provenir des GitHub Actions du commit qui met à jour ce fichier, jamais d'une déclaration manuelle.

## Candidat fonctionnel immédiatement précédent

- SHA : `ea18cca9090c31e3cd6bf7b133886d6e31777b43`
- Objet : code/runtime/tests de clôture, avec release Windows portable configurée pour annuler les builds de `main` devenus obsolètes et certifier prioritairement le HEAD courant.

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
- Les builds portables obsolètes de `main` sont annulés lorsqu'un nouveau HEAD doit être certifié, afin qu'un ancien SHA ne bloque pas la release courante.

## Régressions corrigées juste avant certification

1. Les tests du lanceur vérifient désormais `& $PythonExe -m hl_observer ...` au lieu de réimposer un `python` global.
2. Le test legacy arbitrage vérifie `HYPERSMART_ARB_DISLOCATION_PAPER=0` au lieu de réactiver la v1.
3. Le coût stress deux jambes corrige l'arithmétique : 36 bps × 100 USD × 2 jambes = 0.72 USD.
4. Le test DATA_MISSING sans jambes d'entrée exige l'absence de `CLOSE` fabriqué et le statut `UNLIQUIDATABLE_DATA_MISSING`.
5. Ce test respecte le contrat réel du store : `pos["id"]` est la clé canonique de `store["ouvertes"]`, tandis que `position_id` reste l'identifiant unique de l'épisode dans la valeur.
6. Les workflows temporaires utilisés pour les réparations chirurgicales ont été supprimés après application.

## Critère de DONE

Ce chantier n'est certifié DONE que si les workflows GitHub obligatoires du SHA de ce document sont terminés avec succès :

- `hypersmart-ci` ;
- `hyperlab-ci` ;
- `labo-continu-ci` ;
- `alpha-factory` ;
- `portable-release-windows`.

## Candidat P0 du 2026-08-12

Le SHA candidat est le commit qui contient cette section. Les corrections et preuves
locales associees sont les suivantes :

- validation portable depuis une extraction d'execution courte avec espaces et accents,
  sans modifier les trois extractions temoins du manifeste ;
- separation des probes negatives intentionnelles de pytest et des ecritures externes
  reelles du produit ;
- smoke read-only obligatoire sur Hyperliquid et Binance public, dYdX legacy optionnel ;
- workflow HyperLab Windows installe les dependances de test puis lance pytest via
  `python -m pytest` ;
- les echecs de release portable publient leurs preuves sans publier une fausse release ;
- scoreboards economiques distincts pour Copy-Vault, Lead-Lag et Cross-Venue v2,
  avec promotion fail-closed et capital paper unique de 1 000 USD.

Verdicts economiques au moment du gel : Copy-Vault `MORE_DATA`, Lead-Lag `MORE_DATA`,
Cross-Venue v2 `KILL`. Ces verdicts ne deviennent pas positifs sans preuves OOS,
forward, placebos, liquidabilite et echantillon suffisant.

Tout rouge doit être analysé depuis son log exact et corrigé avant clôture. Aucun post-commit de documentation ne doit être ajouté après la certification, afin de conserver le même SHA entre le code certifié et le verdict final.

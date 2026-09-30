# Coverage closure status

Ce document suit le chantier de fermeture de couverture **avant runner self-hosted**.

## Contrat

- `main` reste la source de vérité.
- Le périmètre mesuré reste `--source=src`.
- La cible reste **100.0000 % de lignes / 0 ligne manquante**.
- Aucun `--omit`, aucune baisse de baseline et aucun nouveau `pragma: no cover` ne sont utilisés pour maquiller le résultat.
- Le runner économique self-hosted ne doit pas être lancé tant que `hypersmart/technical-perfect` n'est pas vert sur le SHA final.

## Dernière mesure complète certifiée disponible

Sur le SHA `87a710fcd18f0e6a85e4fc8e54c546766221c838` :

- 106 488 statements ;
- 93 529 lignes couvertes ;
- 12 959 lignes manquantes ;
- **87.8305536774 %** ;
- 1 134 fichiers avec au moins un gap.

Cette mesure est volontairement conservée comme point de comparaison. Les commits de fermeture ajoutés ensuite doivent être remesurés avant d'annoncer un nouveau pourcentage.

## Architecture CI

- `hypersmart/security-quality` certifie gouvernance, supply-chain, vulnérabilités et analyse statique.
- `hypersmart/technical-perfect` reste l'autorité du coverage 100 % et de la preuve technique complète 1→775.
- `coverage-parallel-probe` découpe la même suite en huit shards pour accélérer la cartographie des gaps ; il ne réduit pas le périmètre.

## Lots ajoutés après la mesure 87.83 %

- routes dYdX paper/read-only : succès, erreurs et health ; suppression d'un `return` mort ;
- probe Explorer : dry-run, WebSocket, block details, fallback HTTP, déduplication et fail-closed ;
- suppression de fallbacks Python `<3.11` devenus impossibles dans les modèles Explorer/scanner ;
- commandes CLI locales/read-only : doctor, runtime, logs, readiness, archives, scanner et userFills stream mocké ;
- parsers de recherche gratuits : URLs et formats de toutes les sources supportées ;
- extraction leaderboard, import Explorer, snapshots wallets et toutes les raisons de refus de l'opportunity detector.

Aucun de ces lots ne constitue une preuve économique et aucun ordre réel n'est autorisé.

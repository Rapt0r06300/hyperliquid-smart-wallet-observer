# GitHub-hosted Dataset V2 backtests

## Architecture canonique

La seule source dataset autorisée pour les nouveaux replays/backtests est :

`Rapt0r06300/alina-smartflow-datasets-v2`

Le dépôt `Rapt0r06300/hypersmart-datasets` est LEGACY et ne doit jamais être
importé automatiquement dans Dataset V2.

Le dépôt principal Alina contient :
- les collecteurs ;
- les moteurs de replay/backtest ;
- les contrôles de qualité ;
- les lecteurs SAFE-only.

Le dépôt Dataset V2 contient :
- le control plane (catalogue, index, manifests) sur `main` ;
- les données lourdes dans des GitHub Releases immuables ;
- uniquement des données nouvelles collectées après la création de V2.

## Collecte GitHub-hosted

La campagne automatique canonique est :

`.github/workflows/collect-market-data-v2.yml`

dans `alina-smartflow-datasets-v2`.

Elle checkout le `main` courant d'Alina sur un runner GitHub-hosted, sans PC
utilisateur et sans self-hosted runner.

Sources principales :
- Hyperliquid ;
- Binance ;
- Bybit ;
- OKX.

Les fenêtres sont bornées, partitionnées par source/canal/instrument et peuvent
se chevaucher légèrement entre campagnes afin de réduire le risque de trou.

## Données collectées

Selon la disponibilité publique de chaque venue :
- BBO ;
- L2 profond ;
- trades ;
- mark/index/oracle ;
- funding courant et settlements historiques réels ;
- open interest ;
- liquidations ;
- volume ;
- métadonnées instrument (tick size, lot size, minimums, statut) ;
- timestamps exchange/réception/monotone ;
- IDs de connexion et séquences ;
- RTT/offset d'horloge lorsque mesurables.

Aucune valeur absente n'est remplacée par zéro.

## Qualification

Cycle logique :

`INCOMING -> QUARANTINE -> SAFE | REJECT`

Un shard ne peut devenir `SAFE` que si les preuves nécessaires sont présentes :
- SHA-256 et taille ;
- provenance publique/read-only ;
- intégrité (gaps/régressions/désynchronisation) ;
- horodatage causal ;
- contraintes de synchronisation ;
- réconciliation historique quand la famille l'exige ;
- asset GitHub distant revalidé contre son digest.

Les trades/fills ne deviennent pas SAFE sur la seule continuité WebSocket :
ils exigent une réconciliation explicite quand une source de référence existe.

## Publication

Les fichiers lourds sont publiés comme assets de GitHub Releases. Le publisher :
1. construit les manifests depuis les octets réellement collectés ;
2. upload les assets ;
3. relit les métadonnées GitHub ;
4. compare taille + SHA-256 ;
5. seulement ensuite finalise le statut ;
6. publie `RUN_MANIFEST.json`.

Une Release incomplète sans `RUN_MANIFEST.json` n'est pas une source de validation.

## Replays/backtests

Les lecteurs V2 :
- sélectionnent uniquement les entrées `SAFE` ;
- refusent les dépôts étrangers ;
- téléchargent seulement les shards utiles à la fenêtre demandée ;
- revérifient taille et SHA-256 ;
- conservent la provenance de sélection.

Les replays/backtests restent paper/read-only. Aucune collecte ou donnée ne doit
autoriser implicitement une exécution réelle.

## GitHub-hosted uniquement

Les workflows dataset doivent rester :
- `runs-on: ubuntu-latest` ou autre runner GitHub-hosted ;
- sans `self-hosted` ;
- sans accès au PC utilisateur ;
- sans clé de trading ;
- sans endpoint d'ordre.

Les grosses campagnes doivent être découpées en fenêtres/jobs afin de rester
bien sous la limite d'exécution d'un job et de pouvoir relancer seulement le
morceau défaillant.

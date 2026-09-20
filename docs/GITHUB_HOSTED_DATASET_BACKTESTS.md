# GitHub-hosted dataset backtests

## Architecture canonique

Le dépôt public Alina SmartFlow fournit les moteurs de replay/backtest et les ponts de données.

Le dépôt privé :

`Rapt0r06300/hypersmart-datasets`

reste le **control plane** des données lourdes et des exécutions GitHub-hosted. Le workflow canonique de lancement est :

`.github/workflows/github-hosted-backtest.yml`

dans le dépôt privé datasets.

Cela évite de faire transiter les données privées par un workflow du dépôt public et permet au workflow privé d'utiliser son propre `GITHUB_TOKEN` pour lire ses Releases.

## Ce que cette branche ajoute au moteur Alina

- matérialisation FULL/COLD en streaming avec `--stream-assets` ;
- téléchargement/vérification d'un asset à la fois ;
- purge de l'asset temporaire après reconstruction ;
- vérification SHA-256 des fichiers reconstruits ;
- pont `continuous_vault` vers les snapshots incrémentaux GitHub ;
- CLI `python -m hl_observer.ops.continuous_vault` ;
- compatibilité du workspace Continuous Vault avec les runners économiques existants ;
- mémoire cumulative permettant de conserver des données déjà archivées même lorsqu'elles ne sont plus présentes localement.

## Sources de données

Deux couches GitHub sont complémentaires :

- **FULL/COLD** : snapshot historique massif, Release privée ID `371149058` ;
- **Continuous Vault** : nouveaux snapshots incrémentaux immuables, référencés par `catalog/CONTINUOUS_VAULT_POINTER.json` après le premier backup autorisé.

Le bridge Continuous Vault sait lire plusieurs Releases historiques parce que chaque fichier de l'index porte son `release_tag`.

## Suites

Les suites restent celles du `dataset_bridge` existant :

- `economic-core`
- `economic-full`
- `copy-vault-full`
- `lead-lag-full`
- `cross-venue-full`
- `microstructure-full`
- `research-lab-full`
- `sqlite-core`
- `sqlite-all-safe`

Aucune stratégie parallèle n'est créée.

## Disque des runners GitHub

Le mode `--stream-assets` réduit le pic de stockage :

1. télécharger un asset ;
2. vérifier son SHA-256 ;
3. reconstruire les fichiers utiles ;
4. vérifier les fichiers reconstruits ;
5. supprimer l'asset temporaire ;
6. passer au suivant.

Le pic disque est donc proche de :

`volume brut sélectionné + plus gros asset + réserve`

au lieu de :

`volume brut sélectionné + tous les assets téléchargés`.

Une suite qui dépasse malgré tout l'espace d'un runner GitHub-hosted échoue proprement ; aucune donnée n'est tronquée silencieusement.

## Sécurité

Les runners économiques restent paper/read-only. Les workflows privés doivent continuer à imposer :

- mainnet execution = 0 ;
- testnet execution = 0 ;
- real trading = false ;
- aucune collecte live pendant les replays ;
- vérification des SHA-256 ;
- plafond de téléchargement ;
- artefacts de sortie limités aux rapports/verdicts.

Les données brutes restent dans le dépôt privé datasets / ses Releases.

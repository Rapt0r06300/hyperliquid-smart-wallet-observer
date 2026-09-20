# GitHub-hosted dataset backtests

## But

Permettre à Alina SmartFlow de lancer des replays/backtests directement sur les runners GitHub hébergés, sans utiliser le portable.

Le workflow est :

`.github/workflows/alina-dataset-backtest-github.yml`

Il est **manuel uniquement** et réservé à l'acteur GitHub `Rapt0r06300`.

## Source des données

Les données lourdes restent dans le dépôt privé :

`Rapt0r06300/hypersmart-datasets`

Le workflow utilise le pont datasets existant d'Alina et le secret de lecture :

`ALINA_DATASET_READ_TOKEN`

La Release FULL/COLD canonique actuelle reste la Release ID `371149058`.

Chaque asset téléchargé est vérifié par le mécanisme datasets existant avec taille + SHA-256.

## Suites disponibles

- `economic-core`
- `economic-full`
- `copy-vault-full`
- `lead-lag-full`
- `cross-venue-full`
- `microstructure-full`
- `research-lab-full`
- `sqlite-core`
- `sqlite-all-safe`

Le workflow calcule le plan exact avant téléchargement et refuse de dépasser `max_download_gib`.

## Exécution

Pour `economic-core` et `economic-full`, le workflow appelle le runner économique canonique :

`tools/run_dataset_economic_campaigns.py`

Pour les autres suites, il utilise :

`python -m hl_observer.ops.dataset_research_runner`

Aucune nouvelle stratégie parallèle n'est créée.

## Sécurité

Le workflow impose :

- mainnet execution = 0 ;
- testnet execution = 0 ;
- real trading = false ;
- mode paper/read-only ;
- `HYPERSMART_ANALYSIS_LOCAL_ONLY=1` ;
- `--no-start-collection` pour le runner économique ;
- aucun self-hosted ;
- aucune utilisation du portable.

## Espace disque GitHub

Les runners GitHub-hosted ont un espace disque limité. Le workflow supprime uniquement des toolchains préinstallées inutiles du runner éphémère afin de récupérer de l'espace.

Les suites très lourdes peuvent encore dépasser la capacité d'un runner standard. Le workflow échoue alors proprement au niveau du disk guard / plafond de téléchargement ; il ne tronque jamais silencieusement les données.

Le prochain chantier consiste à ajouter un mode de matérialisation streaming afin de réduire le pic disque pour les suites `economic-full` et `lead-lag-full`.

## Résultats

Les données privées reconstruites restent uniquement dans l'espace éphémère du runner.

L'artefact GitHub public du run contient seulement :

- rapports ;
- verdicts compacts ;
- métadonnées de run.

Il n'upload jamais les données brutes privées dans le dépôt public Alina.

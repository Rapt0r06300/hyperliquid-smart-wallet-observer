# GitHub-hosted dataset jobs

## Pourquoi

Le dépôt privé `Rapt0r06300/hypersmart-datasets` reste la source des données, mais ses jobs GitHub-hosted peuvent être refusés avant la première étape.

Ce workflow fournit un chemin de calcul **sans PC** depuis le dépôt public, en utilisant le secret de lecture privé déjà prévu par Alina.

Workflow :

`.github/workflows/alina-github-dataset-job.yml`

## Déclenchement

Un job est lancé uniquement lorsqu'un commit sur `main` ajoute exactement un fichier :

`control/github_dataset_jobs/*.json`

Le commit ne doit contenir aucun autre changement.

Exemple :

```json
{
  "schema": "alina.github_dataset_job.v1",
  "job_id": "copy-vault-prepare-001",
  "source": "full-cold",
  "suite": "copy-vault-full",
  "mode": "prepare-only",
  "max_download_gib": 5
}
```

## Sources

- `full-cold` : Release privée historique `371149058`
- `continuous` : dernier pointeur Continuous Vault privé, après le premier backup autorisé

## Modes

- `prepare-only` : vérifie l'accès, calcule le plan et matérialise la suite
- `economic` : lance le runner économique canonique sur `economic-core` ou `economic-full`
- `historical` : lance le laboratoire historique standard
- `historical-full` : ajoute les validations historiques longues

## Sécurité

- runner `ubuntu-latest` uniquement ;
- actor `Rapt0r06300` uniquement ;
- branche `main` uniquement ;
- secret `ALINA_DATASET_READ_TOKEN` requis ;
- mainnet/testnet execution désactivés ;
- aucune collecte live dans le runner économique ;
- FULL/COLD matérialisé avec `--stream-assets` ;
- les données privées restent sous `RUNNER_TEMP` / `ALINA_DATASET_HOME` ;
- aucun dataset brut n'est inclus dans l'artifact ;
- aucun chemin ni rapport issu du dataset privé n'est copié dans l'artifact public ;
- les sorties détaillées de préparation restent uniquement dans l'espace éphémère du runner ;
- l'artifact public contient seulement une preuve synthétique allowlistée : `job_id`, `source`, `suite`, `mode`, `success`, `file_count`, `total_bytes`, `paper_only`, `real_execution`, `raw_dataset_uploaded`, `dataset_paths_uploaded`, `dataset_reports_uploaded`.

Ce workflow utilise un chemin de contrôle différent des workflows self-hosted :

- pas `control/alina_jobs/`
- pas `control/alina_final_jobs/`
- pas `research/queue/`

Il ne peut donc pas réveiller le runner PC par les déclencheurs existants.


## État vérifié au 20 septembre 2026

Le premier smoke GitHub-hosted a atteint le garde d'accès privé puis s'est arrêté exactement sur l'absence du secret `ALINA_DATASET_READ_TOKEN`.

Un probe séparé a testé le `GITHUB_TOKEN` natif du dépôt public contre :

`Rapt0r06300/hypersmart-datasets`

Résultat : **HTTP 404**. Le token natif du dépôt public ne peut donc pas lire le dépôt privé frère.

Conséquence : le dernier prérequis externe est réellement un jeton de lecture inter-repo stocké dans le secret Actions :

`ALINA_DATASET_READ_TOKEN`

Le jeton doit être limité au dépôt privé `Rapt0r06300/hypersmart-datasets` et à la lecture des contenus/releases nécessaires aux datasets. Aucun droit d'écriture n'est requis pour le workflow public de replay/backtest.

Le connecteur GitHub utilisé depuis ChatGPT ne donne volontairement pas accès aux APIs GitHub Secrets ; ce secret ne peut donc pas être créé depuis cette conversation.

Le contrôle smoke déjà ajouté :

`control/github_dataset_jobs/copy-vault-prepare-20260920.json`

reste une preuve historique de ce garde-fou. Une nouvelle requête immuable devra être ajoutée après configuration du secret pour refaire le smoke.

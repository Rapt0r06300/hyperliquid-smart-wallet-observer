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
- l'artifact contient uniquement plan, provenance et rapports.

Ce workflow utilise un chemin de contrôle différent des workflows self-hosted :

- pas `control/alina_jobs/`
- pas `control/alina_final_jobs/`
- pas `research/queue/`

Il ne peut donc pas réveiller le runner PC par les déclencheurs existants.

# File de commandes Alina self-hosted

Ce dossier est le **plan de contrôle versionné** du laboratoire HyperSmart qui tourne sur le PC Windows self-hosted.

## Principe

Un nouveau fichier `*.json` commité sur `main` dans ce dossier déclenche `.github/workflows/alina-self-hosted.yml`.

La chaîne est :

`GitHub main -> commande JSON -> runner self-hosted Windows -> ALINA_RESEARCH_HOME -> worker autonome -> backtests/replays -> petits rapports GitHub`.

Les données brutes, caches, workspaces et gros logs restent sur le PC dans `ALINA_RESEARCH_HOME`.

## Sécurité

Le JSON de contrôle ne peut pas activer le trading réel, le testnet, la collecte live ou changer de dépôt de données. `src/hl_observer/ops/self_hosted_control.py` reconstruit une requête canonique et impose :

- `project_ref=main` ;
- SHA exact du commit qui déclenche le workflow ;
- `paper_only=true` ;
- `real_execution=false` ;
- `start_live_collection=false` ;
- release et dépôt de datasets canoniques ;
- cycle plafonné à 18 heures.

Le workflow ne se déclenche **jamais sur une pull request**.

## Exemple de commande

```json
{
  "schema": "alina.self_hosted_control.v1",
  "job_id": "replay-canonique-001",
  "suite": "economic-full",
  "mode": "economic",
  "download": true,
  "max_download_gib": 20.0,
  "stage_timeout_seconds": 3600,
  "cross_budget_s": 20.0,
  "lead_history_sources": 8,
  "max_cycle_seconds": 64800,
  "force": false,
  "requested_by": "ChatGPT-GitHub",
  "note": "Premier gros run self-hosted."
}
```

Ne pas conserver un fichier d'exemple avec l'extension `.json` dans ce dossier : chaque `*.json` est une vraie demande de travail.

## Gros runs

Une fois le premier replay canonique validé, les commandes peuvent escalader vers les suites `copy-vault-full`, `lead-lag-full`, `cross-venue-full`, `microstructure-full`, `research-lab-full`, `sqlite-all-safe` puis `full-archive`, sous contrôle de l'espace disque et de la politique MAX DATA.

L'objectif économique reste une preuve nette séparée pour chaque famille, sans compensation entre Copy-Vault, Lead-Lag et Cross-Venue et sans utiliser OOS/forward comme gradient de tuning.

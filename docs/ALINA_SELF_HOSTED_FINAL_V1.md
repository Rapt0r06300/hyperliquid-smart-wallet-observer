# Alina SmartFlow — bascule self-hosted FINAL V1

## État avant premier démarrage

Le runner self-hosted final n'est pas encore démarré. Les anciennes commandes sous `control/alina_jobs/` sont considérées comme une file historique potentiellement en attente et ne doivent pas être exécutées par le nouveau runner.

## Isolation de la file historique

Le nouveau workflow est `.github/workflows/alina-self-hosted-final-v1.yml` et le nouveau runner porte le label exclusif `hypersmart-final-v1`.

Les workflows historiques demandent le label `hypersmart`. Le runner FINAL V1 ne porte pas ce label : une ancienne commande ne peut donc pas lui être attribuée.

Le workflow FINAL V1 effectue en plus un contrôle du HEAD courant de `main`. Si son SHA n'est plus le HEAD actuel, il s'arrête avant tout gros calcul avec `SELF_HOSTED_STALE_SHA_REFUSED`.

## Prérequis techniques

Avant le moindre gros backtest/replay sur le PC, le SHA exact doit avoir les trois statuts suivants en `success` :

- `hypersmart/pre-run-775` ;
- `hypersmart/technical-perfect` ;
- `hypersmart/security-quality`.

Le workflow final refuse sinon avec `TECHNICAL_STATUS_NOT_GREEN`.

## Sécurité

Le mode reste strictement paper/read-only. Mainnet, testnet et ordres réels sont désactivés dans le workflow et dans les contrats Python. Les gros logs, datasets et workspaces restent locaux ; seuls les petits retours allowlistés sont remontés sur GitHub.

## Certification économique

Pour une commande `economic-full` / `economic`, le workflow final construit `ALINA_RETURN.json`, utilise la gate économique canonique recalculée et publie le statut :

`hypersmart/economic-3of3`

Ce statut ne peut être vert que si Copy-Vault, Lead-Lag et Cross-Venue sont certifiés séparément. Une famille ne peut jamais compenser le PnL d'une autre.

La cible canonique reste >= 4 USD net éligible par famille avec les preuves exigées : coûts complets, `LIQUIDATABLE_NET`, OOS positif sans look-ahead, forward positif post-freeze, placebo battu, identités/provenance et garde-fous propres à chaque famille.

## Installation du runner final

Le point d'entrée préparé est `INSTALLER_ALINA_RUNNER_FINAL_V1.cmd`, qui appelle `tools/INSTALLER_ALINA_RUNNER_FINAL_V1.ps1` et exige explicitement `GO_SELF_HOSTED=TRUE`.

Ne pas lancer ce runner tant que la commande finale sous `control/alina_final_jobs/` n'a pas été créée sur un HEAD dont les certifications techniques sont vertes.

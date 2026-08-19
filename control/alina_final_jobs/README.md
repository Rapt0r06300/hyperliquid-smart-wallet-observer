# File finale Alina self-hosted v1

Ce dossier `control/alina_final_jobs/` est la **seule file à utiliser pour le premier vrai démarrage self-hosted final**.

## Pourquoi une nouvelle file

Des commandes historiques existent déjà dans `control/alina_jobs/`. Comme le runner n'a pas encore été démarré, d'anciens jobs peuvent rester en attente côté GitHub Actions. Le runner final utilise volontairement le label exclusif `hypersmart-final-v1` et le workflow `.github/workflows/alina-self-hosted-final-v1.yml`.

Les anciens jobs exigent le label historique `hypersmart` : ils ne peuvent donc pas utiliser le runner final.

En plus, le workflow final refuse avant tout gros calcul un job dont le SHA n'est plus le HEAD courant de `main` (`SELF_HOSTED_STALE_SHA_REFUSED`). Une ancienne file ne doit jamais consommer des heures de calcul.

## Conditions obligatoires avant calcul

Le workflow final refuse de lancer les gros backtests/replays tant que le SHA exact n'a pas :

- `hypersmart/pre-run-775=success` ;
- `hypersmart/technical-perfect=success` ;
- `hypersmart/security-quality=success`.

Le runner reste strictement paper/read-only : mainnet, testnet et ordres réels sont bloqués.

## Vérité économique

Pour `suite=economic-full` et `mode=economic`, le retour `ALINA_RETURN.json` recalcule la certification canonique des trois familles séparément.

Le statut GitHub `hypersmart/economic-3of3` ne peut être vert que si **Copy-Vault, Lead-Lag et Cross-Venue sont tous certifiés séparément** avec la cible canonique >= 4 USD net éligible, sans compensation inter-familles, avec coûts complets, liquidabilité, OOS, forward post-freeze, placebo et provenance exigés par la gate canonique.

Si une seule famille échoue, le statut reste rouge et le workflow final se termine par `ECONOMIC_3OF3_NOT_CERTIFIED` après avoir remonté l'artifact public allowlisté pour diagnostic.

## Commandes

Chaque `*.json` ajouté ici est une vraie demande de travail. Ne jamais stocker d'exemple `.json` dans ce dossier.

Une commande finale doit conserver le schéma `alina.self_hosted_control.v1` et les garde-fous de `src/hl_observer/ops/self_hosted_control.py`.

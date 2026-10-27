# Portabilité par clonage du dépôt

Ici, « portable » signifie qu'un clone frais fonctionne depuis le chemin où l'utilisateur l'a placé. Une archive autonome n'est pas nécessaire au parcours opérateur.

## Lanceurs visibles à la racine

- `LANCER_COLLECTEURS_COPY_VAULT.cmd` : collecte Copy-Vault.
- `LANCER_LAB_QUANT_COPY_VAULT.cmd` : backtests et replays Copy-Vault.
- `LANCER_HYPERSMART.cmd` : moteur avec simulation PAPER visible.
- `POUSSER-GITHUB-FORCE.cmd` : réconciliation du code, sans push forcé.
- `ALINA_SYNC_COMPLETE.cmd` et `ALINA_SYNC_COMPLETE.sh` : AlinaSync, y compris l'import des shards SAFE.

Les autres commandes sont rangées dans `tools/launchers/`. Elles calculent la racine du clone à partir de leur chemin ; aucun chemin utilisateur codé en dur n'est requis. Voir `tools/launchers/README.md`.

## Nouveau clone

1. Cloner `Rapt0r06300/hyperliquid-smart-wallet-observer` dans le dossier souhaité.
2. Préparer Python à partir des instructions du `README.md`.
3. Lancer AlinaSync pour récupérer les données SAFE publiées, avec les options de téléchargement adaptées au volume disponible.
4. Lancer les collecteurs, le laboratoire ou le moteur depuis leurs commandes à la racine.

Le code et les données restent séparés : `POUSSER-GITHUB-FORCE.cmd` synchronise le code ; AlinaSync récupère les shards SAFE. Les shards ne sont pas inclus dans un clone Git ordinaire.

Toute simulation reste `PAPER / READ-ONLY / FAIL-CLOSED`. Un clone fonctionnel ou un replay positif ne constitue pas une preuve économique ; le verdict dépend des données causales, des coûts et des contrôles OOS/forward canoniques.
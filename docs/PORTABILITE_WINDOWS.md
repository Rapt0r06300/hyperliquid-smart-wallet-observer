# Portabilité par clonage du dépôt

Ici, « portable » signifie qu'un clone frais fonctionne depuis le chemin où l'utilisateur l'a placé. Une archive autonome n'est pas nécessaire au parcours opérateur.

## Lanceurs visibles à la racine

- `LANCER_COLLECTEURS_COPY_VAULT.cmd` : collecte Copy-Vault.
- `LANCER_LAB_QUANT_COPY_VAULT.cmd` : backtests et replays Copy-Vault.
- `LANCER_HYPERSMART.cmd` : moteur avec simulation PAPER visible.
- `POUSSER-GITHUB-FORCE.cmd` : réconciliation du code, sans push forcé.
- `ALINA_SYNC_COMPLETE.cmd` et `ALINA_SYNC_COMPLETE.sh` : AlinaSync, y compris l'import des shards SAFE.

Les autres commandes sont rangées dans `tools/launchers/`. Elles calculent la racine du clone à partir de leur chemin ; aucun chemin utilisateur codé en dur n'est requis. Voir `tools/launchers/README.md`.

## Laboratoire Copy-Vault : modes et performance

Le laboratoire principal est entièrement local et fonctionne en
`PAPER / READ-ONLY / FAIL-CLOSED` :

```cmd
LANCER_LAB_QUANT_COPY_VAULT.cmd
LANCER_LAB_QUANT_COPY_VAULT.cmd safe
LANCER_LAB_QUANT_COPY_VAULT.cmd once
LANCER_LAB_QUANT_COPY_VAULT.cmd preflight
LANCER_LAB_QUANT_COPY_VAULT.cmd tests
```

Le mode sans argument et le mode `safe` lancent le laboratoire continu : après
le batch courant, le processus reste ouvert pour détecter une nouvelle version
SAFE. Le mode `once` lance un seul passage borné puis termine avec son code
retour. `preflight` vérifie les modules, le freeze et les frontières SAFE sans
lancer de recherche économique. `tests` exécute les groupes de tests du
lanceur. Aucun de ces modes ne lance d'ordre, de testnet, de téléchargement ou
de collecte.

L'audit des shards SAFE recalcule toujours le SHA-256 complet de chaque shard
admissible. Pour réduire le temps d'ouverture des nombreux petits fichiers
Windows, ces lectures sont parallélisées dans un pool CPU borné à quatre
workers via `ALINA_QUANT_HASH_WORKERS=4`. Le plafond reste quatre même sur une
machine plus puissante. Cette optimisation ne réutilise pas une simple taille,
date ou inode : une modification d'un seul octet reste détectée et rejetée.

La mesure de référence du 5 novembre 2026 a vérifié `15 256/15 256` shards,
recalculé `15 256` hashes et exécuté `128` essais dans le run borné en environ
`1 min 44 s`, contre environ `4 min 48 s` avant l'optimisation. Le nombre de
stratégies, `max_trials=128` et l'espace de recherche restent inchangés. Les
rapports JSON exposent `hash_workers`, `hashing_mode` et
`hashes_recomputed`. Cette accélération est technique : elle ne constitue pas
une preuve économique et ne modifie aucun octet SAFE.

## Nouveau clone

1. Cloner `Rapt0r06300/hyperliquid-smart-wallet-observer` dans le dossier souhaité.
2. Préparer Python à partir des instructions du `README.md`.
3. Lancer AlinaSync pour récupérer les données SAFE publiées, avec les options de téléchargement adaptées au volume disponible.
4. Lancer les collecteurs, le laboratoire ou le moteur depuis leurs commandes à la racine.

Le code et les données restent séparés : `POUSSER-GITHUB-FORCE.cmd` synchronise le code ; AlinaSync récupère les shards SAFE. Les shards ne sont pas inclus dans un clone Git ordinaire.

Toute simulation reste `PAPER / READ-ONLY / FAIL-CLOSED`. Un clone fonctionnel ou un replay positif ne constitue pas une preuve économique ; le verdict dépend des données causales, des coûts et des contrôles OOS/forward canoniques.

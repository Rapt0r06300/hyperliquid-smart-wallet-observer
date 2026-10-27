# Topologie des lanceurs Alina Smart Flow

Le registre exécutable est `src/hl_observer/ops/entrypoint_topology.py`. À la racine du dépôt, les seuls fichiers `.cmd` destinés à l'opérateur sont :

| Lanceur | Rôle |
|---|---|
| `LANCER_COLLECTEURS_COPY_VAULT.cmd` | Collecteurs Copy-Vault |
| `LANCER_LAB_QUANT_COPY_VAULT.cmd` | Laboratoire principal : backtests et replays Copy-Vault |
| `LANCER_HYPERSMART.cmd` | Moteur paper avec affichage de simulation |
| `POUSSER-GITHUB-FORCE.cmd` | Réconciliation prudente du code avec GitHub |
| `ALINA_SYNC_COMPLETE.cmd` | AlinaSync pour les shards SAFE |

`ALINA_SYNC_COMPLETE.sh` reste également à la racine pour les clones utilisés sous Linux/macOS. La portabilité signifie ici qu'un clone fonctionne quel que soit son chemin local ; elle ne dépend pas de la création d'une archive portable.

Les autres `.cmd` et le script de restauration Unix sont rangés dans `tools/launchers/`. Ils y restent disponibles pour les workflows, diagnostics, compatibilité et restauration. Ils déterminent la racine du dépôt depuis leur propre emplacement et ne supposent aucun chemin machine fixe. `tools/launchers/README.md` en donne l'inventaire.

`tools/ranger_racine.py` est un audit en lecture seule : il signale les écarts à cette liste et ne déplace ni ne supprime de fichier.

Tous les lanceurs économiques restent `PAPER / READ-ONLY / FAIL-CLOSED`. La racine n'active qu'une seule famille économique : Copy-Vault.
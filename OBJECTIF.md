# OBJECTIF — Copy-Vault Alina Smart Flow

Ce fichier est un rappel opérateur compact. En cas de divergence, l'ordre d'autorité est `SECURITY.md`, la constitution, la spec canonique, le HEAD réel, `AGENTS.md`, puis `CLAUDE.md` et ce résumé.

## Mission active

Faire progresser **Copy-Vault uniquement** au moyen de données publiques et de shards SAFE vérifiés. Tout reste `PAPER / READ-ONLY / FAIL-CLOSED` : aucun ordre réel ou testnet, aucune signature, aucune clé, aucun transfert de fonds. 3x4, arbitrage, Lead-Lag, Cross-Venue, Carry et toute autre famille économique sont hors scope.

## Rôles des lanceurs retenus

- `LANCER_COLLECTEURS_COPY_VAULT.cmd` : collecteurs Copy-Vault ; provenance, horloges, gaps, recovery et admission SAFE doivent rester traçables.
- AlinaSync, via `ALINA_SYNC_COMPLETE.cmd` : restauration/import des shards SAFE depuis les publications GitHub. Les shards ne font pas partie du push Git de code.
- `LANCER_LAB_QUANT_COPY_VAULT.cmd` : cerveau de recherche local sur les données SAFE ; replays/backtests, comparaison contrôlée et archivage durable de chaque amélioration/candidat, y compris les essais non gagnants.
- `LANCER_HYPERSMART.cmd` : moteur avec affichage de simulation paper. Le runtime doit respecter le scope Copy-Vault, même si des surfaces historiques restent dans le dépôt.
- `POUSSER-GITHUB-FORCE.cmd` : sauvegarde/réconciliation prudente du code local vers GitHub ; aucun push force, reset destructif ou transfert de shards.

Seuls ces quatre lanceurs principaux et AlinaSync restent à la racine ; `ALINA_SYNC_COMPLETE.sh` y reste aussi pour les clones Unix. Les autres commandes sont rangées dans `tools/launchers/`. La portabilité recherchée est le bon fonctionnement d'un clone dans tout chemin local.

Ce sont les rôles attendus. Le nom d'un lanceur ne prouve pas à lui seul que son code réalise correctement le rôle ; toute divergence doit être vérifiée contre le HEAD et corrigée.

## Recherche et preuve

Le labo conserve chaque mesure et variante avec paramètres, identité des données, fenêtre, seed, coûts, rapport et statut ; une meilleure variante ne supprime pas les précédentes. Ne jamais inventer un prix, fill, frais, timestamp, zéro ou PnL. Les statuts restent `PROVEN`, `PROMISING`, `MORE_DATA`, `UNMEASURABLE` ou `REJECTED`.

Le parcours canonique est `IDLE → COLLECT → ANALYZE`, puis `DRAIN → QUALITY → REPLAY → BACKTEST → OOS → FORWARD_PAPER → PNL_PROOF → SCOREBOARD → DONE`. Le +5 USD net/jour sur 200 USD paper est la cible économique terminale, évaluée après les réparations et contrôles ; ce n'est ni une promesse ni un seuil qui autorise à relâcher les gates. Un backtest positif, un candidat gelé ou un workflow vert ne prouve pas la rentabilité.

## Travail local

Pour les tâches locales de cet opérateur, travailler directement dans `C:\Users\flo\Desktop\Projet invest`, sans créer ni utiliser de worktree. Les workflows cloud restent GitHub-hosted et ne dépendent jamais du PC utilisateur.

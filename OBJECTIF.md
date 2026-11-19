# OBJECTIF — Copy-Vault Alina Smart Flow

Dernière mise à jour : **2026-11-19**.

Ce fichier est un rappel opérateur compact. En cas de divergence, l'ordre d'autorité est `SECURITY.md`, la constitution, la spec canonique, le HEAD réel, `AGENTS.md`, puis `CLAUDE.md` et ce résumé.

## Mission active

Faire progresser **Copy-Vault uniquement** au moyen de données publiques et de shards SAFE vérifiés. Tout reste `PAPER / READ-ONLY / FAIL-CLOSED` : aucun ordre réel ou testnet, aucune signature, aucune clé, aucun transfert de fonds. 3x4, arbitrage, Lead-Lag, Cross-Venue, Carry et toute autre famille économique sont hors scope.

Le capital paper opérationnel est **100 USD**, défini en un seul endroit :
`PAPER_EQUITY_USD` dans `src/hl_observer/contrat_paper.py`. **Aucun objectif
chiffré n'est actif** : l'objectif est de maximiser le PnL net causal
reproductible, sans cible fixe, sans plafond de profit et sans seuil terminal,
sous contraintes de risque, coûts, drawdown, exposition, liquidité et capacité.
Une amélioration mesurée reste une preuve de recherche tant qu'elle n'a pas
franchi les gates indépendantes OOS/forward et la preuve comptable canonique.
Le repère historique de +5 USD nets/jour ne survit que comme **référence
d'affichage**, jamais comme gate ; les preuves produites sur 350 ou 200 USD de
capital, ou contre une cible de +4/+5 USD/jour, restent historiques et ne
prouvent pas le contrat actuel.

## Rôles des lanceurs retenus

- `LANCER_COLLECTEURS_COPY_VAULT.cmd` : collecteurs Copy-Vault ; provenance, horloges, gaps, recovery et admission SAFE doivent rester traçables.
- AlinaSync, via `ALINA_SYNC_COMPLETE.cmd` : restauration/import des shards SAFE depuis les publications GitHub. Les shards ne font pas partie du push Git de code.
- `LANCER_LAB_QUANT_COPY_VAULT.cmd` : cerveau de recherche local sur les données SAFE ; replays/backtests, comparaison contrôlée et archivage durable de chaque amélioration/candidat, y compris les essais non gagnants.
- `LANCER_HYPERSMART.cmd` : moteur avec affichage de simulation paper. Le runtime doit respecter le scope Copy-Vault, même si des surfaces historiques restent dans le dépôt.
- `POUSSER-GITHUB.cmd` : sauvegarde/réconciliation prudente du code local vers GitHub ; aucun push force, reset destructif ou transfert de shards.

À la racine restent les quatre lanceurs ci-dessus, AlinaSync (`ALINA_SYNC_COMPLETE.cmd`, plus `.sh` pour les clones Unix) et les lanceurs d'appoint **enregistrés** : `Certificateur Coffre Fort.cmd` et `CERTIFIER_EN_CONTINU.cmd` (scellement du coffre), `SUIVI_COFFRE.cmd`, `RAPPORT-COLLECTEURS.cmd`, `RATTRAPAGE.cmd`, `Noeud-HL.cmd`, `Installer Noeud HL.cmd`. **Tout autre `.cmd` à la racine est interdit** : la liste autorisée est fixée par `tests/test_launcher_unifie.py`. Le reste est rangé dans `tools/launchers/`. La portabilité recherchée est le bon fonctionnement d'un clone dans tout chemin local.

Ce sont les rôles attendus. Le nom d'un lanceur ne prouve pas à lui seul que son code réalise correctement le rôle ; toute divergence doit être vérifiée contre le HEAD et corrigée.

## Recherche et preuve

Le labo conserve chaque mesure et variante avec paramètres, identité des données, fenêtre, seed, coûts, rapport et statut ; une meilleure variante ne supprime pas les précédentes. Ne jamais inventer un prix, fill, frais, timestamp, zéro ou PnL. Les statuts restent `PROVEN`, `PROMISING`, `MORE_DATA`, `UNMEASURABLE` ou `REJECTED`.

Le parcours canonique est `IDLE → COLLECT → ANALYZE`, puis `DRAIN → QUALITY → REPLAY → BACKTEST → OOS → FORWARD_PAPER → PNL_PROOF → SCOREBOARD → DONE`. Il n'y a **aucune cible chiffrée de dollars par jour** : geler chaque amélioration nette mesurée, puis continuer la recherche. Un gel exploratoire n'est pas une certification ; seul un champion validé après OOS/forward post-freeze et coûts complets est promouvable. Les anciennes références +4 USD et +5 USD, sur 200 ou 350 USD paper, sont historiques. Un backtest positif, un candidat gelé ou un workflow vert ne prouve pas la rentabilité.

Le portage (funding) est désormais **mesuré** et non plus déclaré inmesurable : les règlements horaires observés du coffre (famille `funding_history`) chiffrent le coût réellement payé par chaque épisode. Un règlement manquant garde le statut `UNMEASURABLE` avec sa raison — jamais un zéro favorable.

## Travail local

Pour les tâches locales de cet opérateur, travailler directement dans `C:\Users\flo\Desktop\Projet invest`, sans créer ni utiliser de worktree. Les workflows cloud restent GitHub-hosted et ne dépendent jamais du PC utilisateur.

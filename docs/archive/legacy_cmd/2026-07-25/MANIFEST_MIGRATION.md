# Manifeste de migration — lanceur unique `LANCER_HYPERSMART.cmd`

Date : 2026-07-25 18:51 UTC · 28 fichiers archives (non executables, `.cmd.txt`).

**Conservation totale.** Chaque ancien `.cmd` de la racine est copie ici a l'identique
(octet pour octet, SHA-256 dans `SHA256SUMS.txt`) et reste dans l'historique git.
Aucune fonctionnalite supprimee : chacun devient une sous-commande du lanceur unique.
Les originaux ne quittent la racine qu'APRES parite fonctionnelle prouvee sous Windows.

## Table : ancien `.cmd` -> sous-commande du lanceur unique

| Ancien fichier racine | Sous-commande | Role | SHA-256 (debut) |
|---|---|---|---|
| `ARRETER-COLLECTEURS.cmd` | `stop` | arret cible des collecteurs (jamais de kill global) | `35aeaa7d9a7c973e` |
| `AUDIT-MOISSONNEUR.cmd` | `audit-moissonneur` | audit budget/branchement du moissonneur | `d986b24258e1c1f1` |
| `DESINSTALLER-PLANIF-VERIF-OOS.cmd` | `verify-oos uninstall` | retire la tache Windows | `2ac4a5e33c6f2729` |
| `FERMER-MOISSON.cmd` | `moisson stop` | ferme la moisson (par titre de fenetre) | `72d7c50e21de982a` |
| `INSTALLER-PLANIF-VERIF-OOS.cmd` | `verify-oos install` | installe la tache Windows (+ auto au demarrage autopilot) | `fd1b86067c48f8b5` |
| `LANCER-MOISSON-12H.cmd` | `moisson` | moisson 12h + tableau de bord | `475fa7307fc6417c` |
| `LANCER-VERIF-OOS.cmd` | `verify-oos run` | runner du verificateur OOS (appele par la tache Windows) | `fbe231626a78ec58` |
| `MOISSONNER-GITHUB.cmd` | `moisson github` | moissonneur GitHub (args transmis) | `ec7760523ae3dc04` |
| `POUSSER-GITHUB-FORCE.cmd` | `github-push --force` | push force explicite | `2720aba0c4c2cc09` |
| `POUSSER-GITHUB.cmd` | `github-push` | push git explicite | `bdabfee3c3a3d33d` |
| `RAPPORT-DU-JOUR.cmd` | `report` | rapport du jour rapports/RAPPORT_DU_JOUR.md | `799be0804b37b8a7` |
| `REANIMER-COLLECTEURS.cmd` | `collectors` | reanime les collecteurs sans toucher au moteur | `919461afec187a68` |
| `RECHERCHE-SCENARIO-REPLAY.cmd` | `replay` | recherche de scenarios / pepites | `d8631adec035217d` |
| `REDEMARRER-USERFILLS.cmd` | `restart-userfills` | recharge le collecteur userfills (code courant) | `ab107f5d89e01a37` |
| `RELANCER-USERFILLS.cmd` | `restart-userfills` | relance isolee userfills (absorbee par restart-userfills) | `3c9a9060c0575429` |
| `RELIRE-LA-MOISSON.cmd` | `moisson relire` | relit une moisson deja faite | `1f5ccfda480a0f6c` |
| `SONDER-CONFIRMATION.cmd` | `sonde` | sonde de transport read-only (shard B) | `d157488a7ec34805` |
| `TEST-AUDIT-complet.cmd` | `audit` | audit ~180 controles (resultat-audit.md) | `3a26296044f6dc78` |
| `TESTER-NOTIFICATION-OOS.cmd` | `verify-oos test-notif` | test de l'alerte (fenetre + son) | `68b1293a558c670e` |
| `TOUT-TESTER.cmd` | `test` | suite complete (RECAP-COMPLET.md) | `455922b8966513f1` |
| `TUER-ORPHELIN-USERFILLS.cmd` | `kill-userfills` | tue l'orphelin userfills + libere le verrou | `91368c84657b3e39` |
| `VERIF-L2-ONDEMAND.cmd` | `verif-l2` | prouve le lecteur L2 on-demand <1s | `474a173879a9896b` |
| `VERIF-PLANIF-OOS.cmd` | `verify-oos diag` | diagnostic + 1 execution manuelle de la tache | `1e91102a0d7f986f` |
| `VERIFIER-TOUT.cmd` | `self-test` | verification rapide 7 sections | `b871c61eeda15505` |
| `VOIR-MOISSON.cmd` | `moisson voir` | tableau de bord seul | `063f951c55933f37` |
| `VOIR-PREMIER-RAW.cmd` | `premier-raw` | rapport du 1er OPEN/CLOSE RAW_PROBE | `6e7c08b470959909` |
| `_moisson_worker.cmd` | `moisson (inline)` | worker inline dans la sous-commande moisson | `609c5de73122eb09` |
| `_relire_worker.cmd` | `moisson relire (inline)` | worker inline dans moisson relire | `df4541014cd34d61` |

## Restauration d'un ancien fichier (si jamais necessaire)

```
copy docs\archive\legacy_cmd\2026-07-25\<NOM>.cmd.txt  <NOM>.cmd
```
ou via git : `git log --all -- <NOM>.cmd` puis `git checkout <commit> -- <NOM>.cmd`.


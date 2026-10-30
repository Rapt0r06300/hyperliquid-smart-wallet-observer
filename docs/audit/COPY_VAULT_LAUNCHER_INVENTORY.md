# Inventaire des lanceurs Copy-Vault

Audit lecture seule : aucun launcher n'est exécuté, supprimé ou modifié.

- Lanceurs suivis : **191**
- Lanceurs canoniques présents : **4/4**
- Findings canoniques bloquants : **aucun**
- Findings bloquants observés : **SELF_HOSTED**

## Chemins canoniques

| Fonction | Lanceur | Catégorie | Références | Consommateurs | Findings |
|---|---|---|---:|---:|---|
| `copy_vault_collectors` | `LANCER_COLLECTEURS_COPY_VAULT.cmd` | `canonical` | 1 | 30 | aucun |
| `hypersmart_engine` | `LANCER_HYPERSMART.cmd` | `canonical` | 36 | 110 | aucun |
| `copy_vault_lab` | `LANCER_LAB_QUANT_COPY_VAULT.cmd` | `canonical` | 1 | 37 | aucun |
| `git_sync` | `POUSSER-GITHUB-FORCE.cmd` | `canonical` | 3 | 42 | aucun |

## Inventaire complet

| Launcher | Catégorie | Fonction | Références |
|---|---|---|---:|
| `ALINA_SYNC_COMPLETE.cmd` | `auxiliary` | `data_or_git_support` | 1 |
| `ALINA_SYNC_COMPLETE.sh` | `auxiliary` | `data_or_git_support` | 1 |
| `LANCER_COLLECTEURS_COPY_VAULT.cmd` | `canonical` | `copy_vault_collectors` | 1 |
| `LANCER_HYPERSMART.cmd` | `canonical` | `hypersmart_engine` | 36 |
| `LANCER_LAB_QUANT_COPY_VAULT.cmd` | `canonical` | `copy_vault_lab` | 1 |
| `POUSSER-GITHUB-FORCE.cmd` | `canonical` | `git_sync` | 3 |
| `archive/racine-2026-07-11/LANCER_REPLAY_OUVERT.cmd` | `auxiliary` | `research_support` | 0 |
| `archive/racine-2026-07-11/STOP_REPLAY.cmd` | `auxiliary` | `research_support` | 0 |
| `archive/racine-2026-07-11/SUIVRE_REPLAY_4H.cmd` | `auxiliary` | `research_support` | 0 |
| `archive/racine-2026-07-11/_go.cmd` | `auxiliary` | `support` | 0 |
| `archive/racine-2026-07-11/_replay_4h.cmd` | `auxiliary` | `research_support` | 0 |
| `archive/racine-2026-07-11/_replay_sample.cmd` | `auxiliary` | `research_support` | 0 |
| `archive/racine-2026-07-11/_scendb3m.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/ALIMENTER-CARRY-AUTO.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/ANALYSER-599.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/APERCU-DASHBOARD.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/BACKFILL-CANDLES.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/BACKFILL-PROFOND.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/CHECK-112-121.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/CHECK-127.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-130-131.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-145.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-3-ROUGES.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/CHECK-304.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/CHECK-586-598.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-591-599.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-593-FULL.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-593.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/CHECK-594-COMPLET.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-594.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-595-596.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/CHECK-595.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-597.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/CHECK-598-FIX.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-600.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-601.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-COHERENCE.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-CROSS-VENUE.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/CHECK-CTRLC.cmd` | `auxiliary` | `support` | 5 |
| `outils de test/CHECK-DATA.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/CHECK-FINAL.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-H.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-H160.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-IDEA.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-M19.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-MOISSONNEUR.cmd` | `auxiliary` | `support` | 10 |
| `outils de test/CHECK-P.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-SAFETY.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/CHECK-SMOKE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/CHECK-T1B.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/CHECK-X.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/COLLECTER-DEPOTS.cmd` | `auxiliary` | `collection_support` | 1 |
| `outils de test/COLLECTER-LIQUIDATIONS-AUTO.cmd` | `auxiliary` | `collection_support` | 1 |
| `outils de test/COLLECTER-MARKS-AUTO.cmd` | `auxiliary` | `collection_support` | 1 |
| `outils de test/COMPARER-VENUES.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/CONSULTER-MEMOIRE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/COUVERTURE-LIGNES.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/CREER_ARCHIVE_PROPRE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/DEBUG-NOYAU.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/DIAG-598.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/DIAG-BORNES.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/DIFF-CABLAGE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/ECOUTER-FLUX-4H.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/ETAT-112-145.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/FALSIFIER-CASHCAT.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/FINIR-CROSS-VENUE.cmd` | `auxiliary` | `support` | 5 |
| `outils de test/FINIR-H90-H180.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/FINIR-LES-BUGS.cmd` | `auxiliary` | `support` | 4 |
| `outils de test/FINIR-LOT.cmd` | `auxiliary` | `support` | 4 |
| `outils de test/FINIR-TOUS-LES-BUGS.cmd` | `auxiliary` | `support` | 4 |
| `outils de test/FINIR-TOUT.cmd` | `auxiliary` | `support` | 7 |
| `outils de test/G1-LOOKAHEAD.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/G2-NOYAU.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/G2-REGRESSION.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/GH01-INTERRUPTEURS.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/H181-MESURE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/H181-VAINQUEUR.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/IMPROVE-130-131.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/LA-PROFONDEUR.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/LANCER-LE-CARRY.cmd` | `auxiliary` | `support` | 5 |
| `outils de test/LANCER-TOUT.cmd` | `auxiliary` | `support` | 7 |
| `outils de test/LE-VERDICT.cmd` | `auxiliary` | `support` | 4 |
| `outils de test/LES-LEVIERS.cmd` | `auxiliary` | `support` | 4 |
| `outils de test/LISTER-RESTE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/MEGATEST.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/MESURER-3-PISTES.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/MESURER-588.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/MESURER-597.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/MESURER-599.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/MESURER-CARRY-INPUTS.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/MESURER-CARRY-NEUTRE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/MESURER-CROSS-VENUE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/MESURER-FLUX-MM.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/MESURER-H160.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/MESURER-SPREAD-CARNET.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/MESURER_SEUIL_FUNDING.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/PAGE-KAITO.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/POURQUOI-CA-CASSE.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/POURQUOI-ZERO-POSITION.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/Q1-TABLE-EDGE.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/Q2-JAMBES.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/Q2-MESURE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/Q3-AVANT-APRES.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/Q3-TESTS.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/RANGER-LA-RACINE.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/REFAIRE-242.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/RUN-COURT-DIAG.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/SONDER-ARCHIVE-S3.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/SUIVRE-MEGATEST.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/T2-CARRY.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/T2-FALSIFIER.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/T2-TEST.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/T3-CABLAGE-NOPAUSE.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/T3-CABLAGE.cmd` | `auxiliary` | `support` | 5 |
| `outils de test/T3B-CABLAGE.cmd` | `auxiliary` | `support` | 5 |
| `outils de test/T3B-GARDES.cmd` | `auxiliary` | `support` | 2 |
| `outils de test/T3D-PROUVER.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/TEST-EDGE.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/TEST-T1.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/TESTER-COLLECTEURS.cmd` | `auxiliary` | `collection_support` | 5 |
| `outils de test/TOUT-VERIFIER.cmd` | `auxiliary` | `support` | 0 |
| `outils de test/VERDICT-T1.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/VERIF-FIX-CARRY.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/VERIF-TOMBES.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/VERIFIER-BRANCHEMENTS.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/VERIFIER-DONNEES-REPLAY.cmd` | `auxiliary` | `research_support` | 2 |
| `outils de test/VERIFIER-ECOUTE.cmd` | `auxiliary` | `support` | 3 |
| `outils de test/VERIFIER-LE-CARRY.cmd` | `auxiliary` | `support` | 5 |
| `outils de test/VERIFIER-TASKLIST.cmd` | `auxiliary` | `support` | 1 |
| `outils de test/VOIR-CARRY.cmd` | `auxiliary` | `support` | 1 |
| `tools/ALINA_RESEARCH_COCKPIT.ps1` | `auxiliary` | `support` | 0 |
| `tools/CONTROLER_ALINA_RUNNER_WINDOWS.ps1` | `auxiliary` | `support` | 0 |
| `tools/INSTALLER_ALINA_RUNNER_FINAL_V1.ps1` | `auxiliary` | `support` | 4 |
| `tools/INSTALLER_ALINA_RUNNER_WINDOWS.ps1` | `auxiliary` | `support` | 3 |
| `tools/VERIFIER_ALINA_RUNNER_WINDOWS.ps1` | `auxiliary` | `support` | 1 |
| `tools/boucle_collecteur.cmd` | `auxiliary` | `collection_support` | 1 |
| `tools/build_full_folder_release.ps1` | `auxiliary` | `support` | 1 |
| `tools/ci_local.cmd` | `auxiliary` | `support` | 0 |
| `tools/create_clean_archive.ps1` | `auxiliary` | `support` | 0 |
| `tools/create_portable_bundle.ps1` | `legacy` | `support` | 4 |
| `tools/diagnose_ollama.ps1` | `auxiliary` | `support` | 1 |
| `tools/find_locked_runtime_files.ps1` | `auxiliary` | `support` | 1 |
| `tools/hypersmart_simulation_poll_loop.ps1` | `auxiliary` | `support` | 3 |
| `tools/ia_train_loop.ps1` | `auxiliary` | `support` | 2 |
| `tools/install_external_github_repos.ps1` | `auxiliary` | `support` | 0 |
| `tools/install_ollama_optional.ps1` | `auxiliary` | `support` | 1 |
| `tools/install_portable_git.ps1` | `legacy` | `support` | 0 |
| `tools/install_portable_runtime.ps1` | `legacy` | `support` | 2 |
| `tools/launchers/ANALYSER_BACKTESTS_REPLAYS.cmd` | `alias_or_support` | `research_support` | 1 |
| `tools/launchers/ANALYSER_DONNEES_HYPERSMART.cmd` | `alias_or_support` | `support` | 3 |
| `tools/launchers/ANALYSE_HISTORIQUE_COMPLETE.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/Alina-restore.cmd` | `alias_or_support` | `data_or_git_support` | 1 |
| `tools/launchers/BACKUP_LOCAL_ALINA.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/CREER_ARCHIVE_PORTABLE.cmd` | `legacy` | `support` | 1 |
| `tools/launchers/CREER_RELEASE_COMPLETE.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/DIAGNOSTIC_LANCEUR.cmd` | `alias_or_support` | `support` | 5 |
| `tools/launchers/INSTALLER_ALINA_RUNNER_FINAL_V1.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/INSTALLER_ALINA_RUNNER_WINDOWS.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/LANCER-CODEX-RESEARCH.cmd` | `alias_or_support` | `support` | 5 |
| `tools/launchers/LANCER-RECHERCHE-14H.cmd` | `legacy` | `support` | 5 |
| `tools/launchers/LANCER-RECHERCHE-18H.cmd` | `legacy` | `support` | 4 |
| `tools/launchers/LANCER-RECHERCHE-CONTINUE-ADMIN.cmd` | `legacy` | `support` | 1 |
| `tools/launchers/LANCER-RECHERCHE-CONTINUE.cmd` | `legacy` | `support` | 2 |
| `tools/launchers/LANCER_COCKPIT_ALINA.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/LANCER_HYPERLAB.cmd` | `alias_or_support` | `research_support` | 2 |
| `tools/launchers/LANCER_LABO.cmd` | `alias_or_support` | `research_support` | 3 |
| `tools/launchers/LANCER_LABO_180GO.cmd` | `legacy` | `research_support` | 2 |
| `tools/launchers/LANCER_MICRO.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/LANCER_OBJECTIF_4USD.cmd` | `legacy` | `support` | 2 |
| `tools/launchers/LANCER_REPLAY_176GO.cmd` | `legacy` | `research_support` | 2 |
| `tools/launchers/POUSSER_TOUT_LE_TRAVAIL.cmd` | `alias_or_support` | `support` | 0 |
| `tools/launchers/PREPARER_DONNEES_HYPERSMART.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/PREPARER_EXPERIENCE_FULL_COLD.cmd` | `alias_or_support` | `support` | 1 |
| `tools/launchers/PREPARER_GIT_PORTABLE.cmd` | `legacy` | `support` | 1 |
| `tools/launchers/PREPARER_PC_ALINA.cmd` | `legacy` | `support` | 5 |
| `tools/launchers/RECETTE-LANCEUR.cmd` | `alias_or_support` | `support` | 3 |
| `tools/launchers/RECETTE-WINDOWS.cmd` | `alias_or_support` | `support` | 4 |
| `tools/launchers/REPARER_ET_POUSSER.cmd` | `alias_or_support` | `support` | 0 |
| `tools/launchers/RESTORE_ALINA.cmd` | `alias_or_support` | `data_or_git_support` | 1 |
| `tools/launchers/RESTORE_ALINA.sh` | `alias_or_support` | `data_or_git_support` | 1 |
| `tools/launchers/VERIFIER_LAB_AUTONOME_ALINA.cmd` | `alias_or_support` | `research_support` | 2 |
| `tools/launchers/VERIFIER_REPARER_L2_LOCAL.cmd` | `alias_or_support` | `support` | 1 |
| `tools/portable_env.cmd` | `legacy` | `support` | 2 |
| `tools/preparer_python_portable.cmd` | `legacy` | `support` | 3 |
| `tools/publish_full_folder_release.ps1` | `auxiliary` | `support` | 0 |
| `tools/push_github_safe.ps1` | `auxiliary` | `support` | 1 |
| `tools/run_pipeline.cmd` | `auxiliary` | `support` | 4 |
| `tools/smoke_full_folder_installer.ps1` | `auxiliary` | `support` | 1 |
| `tools/start_hypersmart_simulation.ps1` | `auxiliary` | `support` | 5 |
| `tools/stream_loop.ps1` | `auxiliary` | `support` | 0 |
| `tools/voir_dashboard.ps1` | `auxiliary` | `support` | 0 |

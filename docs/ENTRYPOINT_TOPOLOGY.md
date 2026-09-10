# Topologie officielle des entrypoints Windows

Autorité de classification P0-115 pour les `.cmd` racine du HEAD courant. Le registre machine correspondant est `hl_observer.ops.entrypoint_topology`.

## Entry points canoniques

| Fichier | Classe | Rôle canonique |
|---|---|---|
| `LANCER_HYPERSMART.cmd` | `OFFICIAL_RUNTIME` | runtime principal, single-instance, collecteurs read-only et sous-commandes explicites |
| `ANALYSER_BACKTESTS_REPLAYS.cmd` | `OFFICIAL_ANALYSIS` | analyse/replay hors hot path sur session complète vérifiée |
| `LANCER-RECHERCHE-CONTINUE.cmd` | `OFFICIAL_RESEARCH` | worker autonome de recherche, reprenable, sans serveur dupliqué |

Un rôle officiel n'a qu'un seul entrypoint canonique. Les autres `.cmd` sont classés `MAINTENANCE`, `COMPAT`, `LEGACY` ou `ARCHIVE` et ne créent pas un quatrième rôle opérationnel.

## Contrats communs des trois entrypoints officiels

- Python portable via `tools\portable_env.cmd` et `%HYPERSMART_PYTHON%` ;
- `HL_ENABLE_MAINNET_EXECUTION=0` ;
- `HL_ENABLE_TESTNET_EXECUTION=0` ;
- aucune activation d'exécution réelle ;
- le runtime ne lance pas le worker `recherche_continue.py` ;
- le worker recherche ne lance pas le runtime serveur ;
- l'analyse reste hors hot path.

`CREER_ARCHIVE_PORTABLE.cmd` est `MAINTENANCE` mais conserve lui aussi le contrat Python portable et paper-only.

## Inventaire non canonique

- `ANALYSER_DONNEES_HYPERSMART.cmd` — MAINTENANCE
- `ANALYSE_HISTORIQUE_COMPLETE.cmd` — COMPAT
- `CREER_ARCHIVE_PORTABLE.cmd` — MAINTENANCE
- `DIAGNOSTIC_LANCEUR.cmd` — MAINTENANCE
- `INSTALLER_ALINA_RUNNER_FINAL_V1.cmd` — MAINTENANCE
- `INSTALLER_ALINA_RUNNER_WINDOWS.cmd` — COMPAT
- `LANCER-RECHERCHE-14H.cmd` — COMPAT
- `LANCER-RECHERCHE-18H.cmd` — COMPAT
- `LANCER-RECHERCHE-CONTINUE-ADMIN.cmd` — COMPAT
- `LANCER_COCKPIT_ALINA.cmd` — COMPAT
- `LANCER_HYPERLAB.cmd` — COMPAT
- `LANCER_LABO.cmd` — COMPAT
- `LANCER_LABO_180GO.cmd` — COMPAT
- `LANCER_MICRO.cmd` — COMPAT
- `LANCER_OBJECTIF_4USD.cmd` — COMPAT
- `LANCER_REPLAY_176GO.cmd` — COMPAT
- `POUSSER-GITHUB-FORCE.cmd` — LEGACY
- `POUSSER_TOUT_LE_TRAVAIL.cmd` — LEGACY
- `PREPARER_DONNEES_HYPERSMART.cmd` — MAINTENANCE
- `PREPARER_EXPERIENCE_FULL_COLD.cmd` — MAINTENANCE
- `PREPARER_GIT_PORTABLE.cmd` — MAINTENANCE
- `PREPARER_PC_ALINA.cmd` — MAINTENANCE
- `RECETTE-LANCEUR.cmd` — MAINTENANCE
- `RECETTE-WINDOWS.cmd` — MAINTENANCE
- `REPARER_ET_POUSSER.cmd` — LEGACY
- `VERIFIER_LAB_AUTONOME_ALINA.cmd` — MAINTENANCE

La gate échoue fermée si un nouveau `.cmd` racine apparaît sans classification, si un fichier enregistré disparaît sans mise à jour du registre, ou si un entrypoint officiel perd son contrat portable/paper-only.

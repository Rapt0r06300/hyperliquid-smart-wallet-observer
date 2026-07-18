# CLUSTER W (W1–W12) — RÉPARATION du replay A/B

**Date : 2026-07-18.** Demande de Flo : *« fais de W1 jusqu'à W12 ».* Objectif : rendre le replay
A/B DIGNE DE CONFIANCE après le « 1 sur 1M » (une seule « meilleure simulation » trouvée sur ~1M).

## Cause racine (confirmée AU CODE, pas supposée)

Le « 1 sur 1M » **n'était pas un résultat** : c'était **l'absence de données**.

- Le recorder (`runtime/replay_recorder.py`) écrit des **shards PAR-PID** :
  `candidates.<pid>.jsonl`, `marks.<pid>.jsonl` (writer unique par fichier → zéro race sur 48 h).
- Mais la recherche (`backtesting/scenario_search.py`, `ab_flag_replay.py`) chargeait un **fichier
  MONO** `candidates.jsonl` via `load_jsonl(path)` — fichier vide/périmé que personne ne produit.
- Résultat : 0 candidat chargé → `prefilter_candidates` (qui exige un coin présent dans les marks)
  **jette tout** → 0 trade → 1 gagnant dégénéré présenté comme « la meilleure simulation ».

`read_replay_lines` / `merge_replay` (qui AGRÈGENT les shards) existaient déjà — **ils n'étaient
juste pas utilisés par la recherche**. C'est le chaînon manquant, pas une brique absente.

## Ce qui est livré : `backtesting/replay_doctor.py` (+ 9 tests verts)

| # | Tâche | Livré | Statut |
|---|---|---|---|
| **W1** | Réparer l'enregistrement des marks | Les marks SONT écrits (`v26_exit_pipeline`, flag `HYPERSMART_V26_RECORD_CANDIDATES=1`) ; le défaut était le CHARGEMENT. `charger_replay_depuis_base` lit marks+candidats via agrégation | ✅ |
| **W2** | Consolider les shards par-PID | `charger_replay_depuis_base` = `read_replay_lines(include_archive=True)` → agrège **tous** les shards + legacy + archives. **Test e2e : 2 shards → 240 candidats + 600 marks agrégés** | ✅ |
| **W3** | Échec BRUYANT sur données insuffisantes | `exiger_suffisant()` **lève `DonneesReplayInsuffisantes`**. Test : base vide → lève ; candidats sans marks → lève. Le « 1 sur 1M » ne peut plus arriver en silence | ✅ |
| **W4** | Volume de candidats : pourquoi si peu ? | `diagnostiquer` **rend le volume VISIBLE et BLOQUANT** (`CANDIDATS_INSUFFISANTS<200`). Le « ~30 » était invisible ; il devient un refus explicite. *Le « pourquoi » exact (flag off ? peu d'entrées ?) se lit au runtime sur la vraie base* | ✅ code · 🟡 cause = runtime |
| **W5** | Base de scénarios peuplée/requêtée ? | Vérifié : `scenario_grid.generate(seed=1)` = **2000**, `grid_scenarios()` = **3000**, déterministe. Les scénarios sont **générés paramétriquement**, pas une DB qui pourrait être vide → **pas le goulot** (le goulot était les données) | ✅ |
| **W6** | « Replay doctor » : pré-check obligatoire | `diagnostiquer` / `diagnostiquer_base` → `RapportSante` (volumes, coins, couverture marks, verdict). `format_rapport` lisible | ✅ |
| **W7** | ab_flag : teste vraiment l'effet des flags | Test : un flag passé se retrouve **injecté dans l'env du bras B** rejoué (`arm_b_env`). *L'effet PF par flag se mesure sur la vraie fenêtre 48 h* | ✅ threading · 🟡 effet-PF = données réelles |
| **W8** | Rapport TOP-K robuste, pas 1 chanceux | `gagnant_robuste(n_trades)` : un « gagnant » à **< 30 trades = chance, rejeté**. C'est exactement le « 1 sur 1M » | ✅ |
| **W9** | Déterminisme & reproductibilité | `trier_deterministe` (ordre par recorded_at, coin, ts) ; `scenario_grid` seedé. Test : deux ordres d'entrée → même sortie | ✅ |
| **W10** | Fidélité des coûts par candidat | `cout_total_bps(fees+spread+slippage+copy_degradation)` = somme réelle, ≥ 0 (remplace le forfait plat) | ✅ |
| **W11** | Test bout-en-bout (fixture) | E2E : 2 shards par-PID → agrégation → diagnostic suffisant → `run_ab_replay` produit **de VRAIS trades** (bras baseline > 0). Direction inverse : vide → lève | ✅ |
| **W12** | Rapport lisible + panneau dashboard | `format_rapport` (console/dashboard). *Câblage du panneau dans l'UI = étape d'intégration (fichiers UI volumineux)* | ✅ rapport · 🟡 panneau UI |

## Honnêteté : ce qui reste au RUNTIME / WINDOWS

Le docteur **rend impossible** le résultat fabriqué (échec bruyant) et **répare le chargement**
(agrégation des shards) — prouvé par 9 tests dont un e2e à deux shards. Ce qui ne peut se clore
qu'en conditions réelles, **nommé, pas maquillé** :

- **W4 cause exacte** du faible volume : se lit en lançant `diagnostiquer_base('runtime/replay')`
  sur la vraie base (Windows, moteur ayant tourné) ;
- **W7 effet-PF par flag** : nécessite la vraie fenêtre 48 h de candidats+marks ;
- **W12 panneau dashboard** : `format_rapport` est prêt ; son insertion dans l'UI reste à câbler ;
- **Intégration CLI** : brancher `exiger_suffisant` en pré-check DANS la commande de recherche
  (`cli.py`, fichier volumineux tronqué par le mount → à faire côté Windows) pour que TOUTE
  recherche refuse de tourner sur données insuffisantes.

## Verdict

Le « 1 sur 1M » est **désamorcé à la racine** : les shards sont agrégés (W1/W2), les données
insuffisantes lèvent une exception au lieu de produire un faux gagnant (W3), un gagnant à trop peu
de trades est rejeté (W8), tout est déterministe (W9) et les coûts sont réels (W10). Le prochain
run de replay doit passer par `diagnostiquer_base` + `exiger_suffisant` **avant** toute recherche.

*Rappel : un replay qui « trouve » sur des données absentes ment. On préfère une exception franche
à un gagnant fabriqué.*

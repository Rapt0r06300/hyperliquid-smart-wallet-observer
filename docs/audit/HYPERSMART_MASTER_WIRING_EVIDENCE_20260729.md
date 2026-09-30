# HYPERSMART — MATRICE DE PREUVE DE CÂBLAGE (2026-07-29)

HEAD de mesure : `0420753` (bloc 18). Mesure produite par `python tools/auditer_cablage.py`,
rapport brut : `data/reports/audit_cablage.json`.

> **Règle appliquée dans tout ce document.** Un statut `DONE_VERIFIED` n'est écrit que si j'ai, **dans ce
> run**, exécuté le test ou l'appel qui le prouve. Tout ce que je n'ai pas revérifié moi-même porte
> `A_REVALIDER` avec sa source — pas `DONE`. Un audit qui recopie d'anciens `DONE` ne mesure rien.

---

## 1. Dette de câblage — chiffres RÉELS au HEAD

| Catégorie | Compte | Sens |
|---|---:|---|
| Orphelins (aucun appelant) | **101** | code présent, jamais atteint |
| Testés mais non branchés | **372** | le test est le seul appelant |
| Outillés (recherche, joignables par un outil) | **143** | légitime si assumé `RESEARCH_ONLY_JUSTIFIED` |
| Interrupteurs morts | **1** | flag lu sans producteur, ou posé sans lecteur |
| Interrupteurs vivants | **62** | flag avec producteur ET lecteur |
| Modules illisibles | **0** | — |
| `fiable` / `real_execution` | `True` / **`False`** | l'audit se déclare fiable, et aucune exécution réelle |

Cliquet : `PLAFOND_DETTE = 61` dans `src/hl_observer/audit/dette_cablage.py`. **Il ne remonte jamais** ; il
baisse en branchant ou en enterrant. Ce run n'a pas augmenté la dette : les 6 modules ajoutés
(ALPHA-5→8, bloc 18) arrivent **avec leur test et leur appelant** ou sont explicitement `RESEARCH_ONLY`.

**Lecture honnête.** 372 modules « testés non branchés » est le chiffre qui compte : c'est la maladie
documentée du projet (« mention ≠ porte »). Il n'a pas été résorbé dans ce run et ne doit pas être présenté
comme réglé.

---

## 2. IDEA-1 → 91 — implémentation canonique et appelant

| Groupe | Implémentation canonique | Appelant réel | Test | Statut |
|---|---|---|---|---|
| 1, 2, 4 (dataset tick, RAW→CANONICAL, snapshot/incrémental) | `collection/tick_dataset.py`, `normalization/market_events.py` | `tools/collecter_bbo.py`, `market_truth/pipeline.py` | `test_tick_dataset`, `test_canonical_market_events` | `DONE_VERIFIED` (rejoué ce run) |
| 3, 5, 6 (gate qualité, stale/gap/outlier, score) | `realtime/feed_quality.py` (+ `feed_quality_reader`) | `collecter_bbo.py`, `decision_engine/local_engine.py`, `noyau_unique.py` | `test_feed_quality_gate`, `test_feed_quality_reader` | `DONE_VERIFIED` (rejoué ce run) |
| 7, 8 (démarrage étalé, reconnexion) | `tools/demarrage_etale.py`, superviseur | `superviseur_collecteurs` | `test_superviseur_collecteurs` | `A_REVALIDER` — non rejoué individuellement ce run |
| 9, 10 (dédup durable, journal opérationnel) | `tools/dedup_durable.py`, `tools/journal_operationnel.py` | `tools/cablage_idees.py` → `recherche_continue` (**LEGACY**) | `test_cablage_idees` | `TODO_ACTIVE` — protection encore côté legacy, à porter |
| 11, 36, 80 (TruthReconciler, ledger corrompu, verrou synthétique) | `market_truth/truth_chain.py`, `tools/pnl_verite.py` | `market_truth_replay` (analyse), `cablage_idees` (legacy) | `test_market_truth_pipeline`, `test_market_truth_replay_stage` | `DONE_VERIFIED` côté analyse ; `TODO_ACTIVE` côté runtime |
| 12-21 (prix exécutable, VWAP, fills partiels, coûts) | `market_truth/executable_replay.py` | `market_truth/pipeline.py`, étape `market_truth_replay` | `test_market_truth_pipeline`, bloc 17 | `DONE_VERIFIED` (rejoué ce run) |
| 22-26 (latence, edge decay, timings, break-even) | `tools/execution_realiste.py` | outil d'analyse | `test_idees_p0_execution_ledger` | `RESEARCH_ONLY_JUSTIFIED` |
| 27-35 (forward causal, ledger, crash recovery) | `tools/forward_causal.py`, `tools/ledger_verite.py`, `market_truth` | `market_truth` pour 33-35 | bloc 17 (`test_forward_causal_parity_bloc17`) | `DONE_VERIFIED` pour l'idempotence et la parité ; `RESEARCH_ONLY` pour le reste |
| 37-40 (validation éco, ROI, mark causal, DD) | `ops/economic_revalidation.py` (**ce run**), `ops/pnl_improvement_lab.py` | étapes de `historical_analysis_suite` | `test_economic_revalidation_bloc18` (20) | `DONE_VERIFIED` |
| 41-51 (étages, walk-forward, PBO, DSR, bootstrap, placebos, ablation) | `backtesting/robustesse_selection.py`, `research_parallel/validation.py`, `tools/rigueur_recherche.py` | `historical_analysis_suite`, ALPHA-5 (`verdict_conditionne`) | `test_idees_36_a_91` | `DONE_VERIFIED` pour DSR/placebo/embargo (utilisés ce run) |
| 52-55 (régimes, tuning coin/horizon) | `tools/regimes_marche.py`, ALPHA-5 `cross_venue_conditions.py` | ALPHA-5 (conditions pré-enregistrées) | `test_cross_venue_conditions_alpha5` | `DONE_VERIFIED` |
| 56-60 (ladder, inventaire, OFI, depletion, toxicité) | `experimental/metaorder_l2_tape.py` | ALPHA-5 et ALPHA-7 (ce run) | `test_metaorder_l2_tape`, `test_metaorder_toxicite_alpha7` | `DONE_VERIFIED` |
| 61-66 (entités, copyabilité, metaorder, lead-lag, cohortes, conflits) | `following/entity_consensus.py`, `experimental/metaorder_shadow.py` | bloc 16, ALPHA-7, ALPHA-8 | `test_entity_consensus`, `test_metaorder_shadow` | `DONE_VERIFIED` |
| 67-70 (stops, time stop, reduce, MAE/MFE) | `tools/exits_risque.py`, ALPHA-8 `copier_reduce` | ALPHA-8 (REDUCE proportionnel) | `test_leader_proportional_sizing_alpha8` | `DONE_VERIFIED` pour REDUCE ; `RESEARCH_ONLY` pour MAE/MFE |
| 71, 78-91 (garde-fous, manifeste, ingestion, synthétique, Punisher) | `tools/garde_fous_recherche.py` | `cablage_idees` (legacy) + tests | `test_idees_36_a_91` | `TODO_ACTIVE` — encore côté legacy |
| 72-77 (idle, scheduler, progression, watchdog, dashboard, rapport) | `tools/jobs_continue.py`, `progres_live.py`, `dashboard_flow.py` | `recherche_continue` (**LEGACY**) | `test_labo_continu_*` | `OBSOLETE_WITH_REASON` — le moteur legacy est gelé ; équivalents dans `historical_analysis_suite` |

**Règle de migration appliquée.** `tools/cablage_idees.py` reste branché sur `recherche_continue.py`
(legacy, gelé). Les idées qui protègent le **runtime/ledger** (9, 10, 11, 36, 71, 78-80) doivent être
portées vers `src/hl_observer` : elles sont marquées `TODO_ACTIVE` ici, **pas** `DONE`. Une protection
critique qui ne vit que dans le legacy ne protège rien.

---

## 3. HS-070 → HS-100

31 identifiants sont référencés par `docs/release/HYPERSMART_MASTER_REPAIR_HS070_HS100.md`.

**Statut honnête : `A_REVALIDER` en bloc.** Je n'ai pas rejoué individuellement les 31 preuves dans ce run.
Les recopier en `DONE` ici reviendrait exactement à ce que la roadmap interdit — déduire un statut d'un
document au lieu d'une mesure. La revalidation demande, par item : localiser l'implémentation, son appelant,
son test, puis exécuter ce test. C'est la première tâche du prochain run.

Ce qui est **prouvé ce run** et recouvre une partie du périmètre HS : l'idempotence du ledger (bloc 17),
la réconciliation économique et l'interdiction du non-mesurable valorisé à 0 (bloc 18), l'absence
d'exécution réelle (`safety-audit` et `audit-safety`, 8/8).

---

## 4. Ce que ce run a réellement ajouté au câblage

| Apport | Module | Appelant / test | Statut |
|---|---|---|---|
| ALPHA-5 conditions causales | `experimental/cross_venue_conditions.py` | registre d'essais + 17 tests | `DONE_VERIFIED` |
| ALPHA-6 NBBO exécutable | `arbitrage/nbbo_synthetique.py` | contrat de sens bloc 2 + 15 tests | `DONE_VERIFIED` |
| ALPHA-7 toxicité/crowding | `experimental/metaorder_toxicite.py` | stades `metaorder_shadow` + 17 tests | `DONE_VERIFIED` |
| ALPHA-8 sizing borné | `copying/leader_proportional_sizing.py` | 22 tests | `DONE_VERIFIED` |
| Bloc 17 parité causale | — (tests) | `market_truth` réel, 11 tests | `DONE_VERIFIED` |
| Bloc 18 revalidation éco | `ops/economic_revalidation.py` | ledgers réels + 20 tests | `DONE_VERIFIED` |

Aucun de ces modules n'ouvre de position ni ne promeut : ALPHA-5/7 plafonnent à `DISCOVERY_PROBE` /
`SHADOW`, ALPHA-6 et ALPHA-8 sont des calculateurs sans effet de bord, le bloc 18 est en lecture seule.

---

## 5. Sécurité

`0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
`safety-audit` et `audit-safety` : **8/8 `ok`** au HEAD. `real_execution=False` dans le rapport de câblage.

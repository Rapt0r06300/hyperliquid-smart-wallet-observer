# MATRICE DE PREUVES — TASKLIST (2026-07-21)

> Une tâche cochée sans preuve est une dette. Cette matrice donne, pour chaque tâche de
> `docs/TASKLIST_ACTIVE.md`, **la commande ou le fichier qui prouve son statut**.
> Version précédente archivée : `docs/archive/TASKLIST_EVIDENCE_MATRIX_20260711_archivee.md`.

| tâche | statut | preuve exécutable / fichier | mesure |
|---|---|---|---|
| P0-1 funding réglé/estimé | `DONE_VERIFIED` | `pytest -q tests/test_funding_settlement.py` | 28 verts ; somme conservée |
| P0-2 source unique PnL | `PARTIALLY_DONE` | `resume_depuis_ledger()` seul agrégateur | MtM base encore dans l'endpoint |
| P0-3 invariant portes replay | `TODO_ACTIVE` | — | aucun test n'échoue si `stress` est retiré |
| P0-4 scénarios PnL | `PARTIALLY_DONE` | `pytest -q tests/test_invariants_economiques.py` | 7 lois / ~700 cas ; 8 scénarios manquants |
| P1-1 économie par position | `TODO_ACTIVE` | `data/reports/carry_position_economics.csv` | 12 lignes, mais hedge **modélisé** |
| P1-2 delta réel | `TODO_ACTIVE` | — | `DATA_MISSING` : quantités par jambe non stockées |
| P1-3 scorecard par coin | `TODO_ACTIVE` | `data/reports/carry_coin_scorecard.json` | 12 × `POSITIVE_BEFORE_COSTS_ONLY` |
| P1-4 mapping Unit officiel | `TODO_ACTIVE` | log feeder | refus `base aberrante ×141` / `×3511` |
| P1-5 allocation ∝ net³ | `DONE_VERIFIED` | `pytest -q tests/test_carry_allocation_nette.py` | 34 verts ; +23,9 % mesuré |
| P1-6 renfort sans churn | `DONE_VERIFIED` | `pytest -q tests/test_carry_renfort.py` | 27 verts, bout-en-bout production |
| P1-7 garde du plancher z-score | `DONE_VERIFIED` | `facteur_zscore(2.5, 0.125) == 1.0` | corrélation −0,596 corrigée |
| P1-8 seuil +0,05 $ vs bruit | `TODO_ACTIVE` | — | bruit ~0,0147 $/h → seuil ≈ 3,4 h de bruit |
| P1-9 backtest carry | `DONE_VERIFIED` | `python tools/backtest_carry_cli.py .` | 24 verts ; garde anti-baisse-de-sécurité |
| P1-10 journal de scans | `DONE_VERIFIED` | `carry_scan_recorder.resume('.')` | 20 coins, 7 passes, en croissance |
| P1-11 stabilité des viables | `BLOCKED_DATA` | idem | 7 passes / 12 minimum |
| P2-1..5 README | `DONE_VERIFIED` | `git diff README.md` | 5 contradictions prouvées corrigées |
| P3-1 critères figés | `DONE_VERIFIED` | `docs/research/CROSS_VENUE_FUNDING_72H_VERDICT.md` | 5 critères écrits avant échéance |
| P3-2 verdict 72 h | `BLOCKED_DATA` | étendue `dispersion_venues.jsonl` | 48,5 h / 72 h |
| P4-1 prix exécutables | `TODO_ACTIVE` | `collecter_dispersion_venues.py` | écart = deux **mids** |
| P4-2 coût all-in décomposé | `PARTIALLY_DONE` | `COUT_AR_BPS = 8.0` | forfait, non décomposé |
| P4-4 convergence mesurée | `DONE_VERIFIED` | `runtime/replay/BACKTEST_ARBITRAGE.md` | −2,26 bps à 30 min, 912 écarts |
| P4-5 cadence ×5 | `DONE_VERIFIED` | `grep 60 LANCER_HYPERSMART.cmd` | 300 s → 60 s |
| P4-6 seuil 15 → 8 bps | `BLOCKED_DATA` | idem | 19 entrées < 10 min. requis ×… |
| P5-1 collecte C12 | `DONE_VERIFIED` | `leader_fills_bruts.jsonl` | 3 947 lignes / 6,8 h |
| P5-2 markout par leader | `PARTIALLY_DONE` | `copy_whitelist.json` | 173 marqués, 12 leaders, 0 à 30 fills |
| P6-1 décision Liquidations | `TODO_ACTIVE` | `liquidation_map.sqlite3` | 231 grappes / 31,6 h |
| P7-1 Grinder/Sniper | `DONE_VERIFIED` | `docs/research/GRINDER_SNIPER_REAL_STATUS.md` | ledger : 0 ligne, 7 termes `NOT_FOUND` |
| P8-3 superviseur | `DONE_VERIFIED` | compteurs au rapport du jour | relances tracées |
| P9-1..5 rapports | `DONE_VERIFIED` | `RECAP-COMPLET.md`, `RAPPORT_DU_JOUR.md` | 8 étapes, 12 sections |

## Tâches ROUVERTES (l'état contredit un ancien rapport)

| tâche | ancien statut | nouveau | raison |
|---|---|---|---|
| README « quatre modules » | présenté comme exact | `CONTRADICTED` puis corrigé | 5 lignes dans le tableau |
| Arbitrage « 35 bps / 22 de coûts » | annoncé | `CONTRADICTED` puis corrigé | code : 15 / 8 bps |
| « funding couru = l'encaissé » | annoncé « stable » | `CONTRADICTED` puis corrigé | prorata linéaire ≠ règlement horaire |
| Liquidations « 0 événement » | annoncé | `CONTRADICTED` puis corrigé | 231 grappes enregistrées |
| Carry « seule source de PnL positif » | annoncé | `PARTIALLY_PROVEN` puis nuancé | taux +0,35 $/j, **cumul −5,73 $** |

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**

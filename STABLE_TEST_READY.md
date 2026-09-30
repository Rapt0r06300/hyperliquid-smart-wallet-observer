# STABLE_TEST_READY

    STABLE_TEST_READY=false

Verdict honnête produit depuis le sandbox cloud (Linux, sans réseau exchange, sans Windows).
Paper strict : 0 ordre réel, 0 clé privée, 0 endpoint `/exchange`, capital fictif ≤ 1000 USD.
Familles actives : Copy-Vault, Lead-Lag, Cross-Venue. Carry = DISABLED_BY_SCOPE.

## Ce qui passe RÉELLEMENT ici (branché + testé + committé, pytest vert)

- Registre machine + gates (blocs 1-4) — `tools/claude_tasks_scan.py`, `CLAUDE_TASKS.jsonl`, 2 gates.
- LIVE_READY : `OFFLINE_READY != LIVE_READY`, 6 critères runtime (13-14).
- Médaillon réel Parquet : Bronze immuable hashé / Silver partitionné / Gold + lineage (29-31),
  catalogue Data Mesh SQLite + migrations (32), data plane E2E (37).
- Collecteurs supervisés + résilience : heartbeat / last_useful_event_ts / backoff / circuit-breaker /
  rate-limit / load-shedding / quota (25-28), DLQ (33).
- Moteur paper UNIQUE + enveloppe 1000 USD partagée ; 3 familles → PaperIntent → fill → ledger (38-46, 71).
- Validation : CPCV, PBO, Deflated Sharpe, SPA bootstrap, placebo, leave-one-out, ablation (47-49).
- Normalisation + versioning point-in-time (34-35) ; parité live/replay + cohérence fast/exact +
  réconciliation 5 vues (36, 53, 54) ; Cross-Venue jambe partielle/manquée/unwind + risque résiduel (41-42) ;
  calibration coûts/slippage/latence depuis mesures (43) ; session COMPLETE + hashes (52) ;
  anti-fuite IS/OOS/forward + gel finalistes (55).
- Orchestrateur unique `hyperlab_master` quick/full/deep/maximum/resume + lanes multi-session/historique (5-7) ;
  CLI `python -m hl_observer.hyperlab smoke` → code retour 0 ; dédup des 2 CMD d'analyse (8) ;
  CI bloquante `pip install -e .` + `requirements-recherche.txt` (9-10) ; WINDOWS_FULL_NIGHTLY (11) ;
  recette Windows double-clic `LANCER_HYPERLAB.cmd` (57).

Total : 54 tests pytest verts (Linux), pyarrow + sqlite + numpy réels. Smoke E2E : `verdict_chaine_ok=true`.

## Blocages EXACTS qui maintiennent le verdict à `false` (non franchissables DANS ce sandbox)

1. **Collecte live read-only réelle** (blocs 15-24, 51) : aucun réseau exchange ici
   (binance / bybit / okx / coinbase / deribit / defillama → HTTP `000`). Le code client REST/WS est écrit,
   mais **non exécuté en live** → non prouvé E2E, donc non DONE sous la barre stricte.
2. **Windows exécuté** : WINDOWS_FULL_NIGHTLY, CMD E2E, recette double-clic *lancés pour de vrai*
   (blocs 11-12, 57-58) : pas de runner Windows dans le sandbox.
3. **Soak 6 h / test stable multi-heures** (blocs 50, 58) : non exécutable dans un appel outil.
4. **CI réellement verte** (blocs 9-10-11-12) : les workflows sont écrits ; GitHub Actions s'exécute
   à **ton push**, pas ici.

## Chemin vers `STABLE_TEST_READY=true` (honnête, sans forcer)

Exécuter, dans un environnement disposant de **réseau + Windows** :

1. Au push : `hyperlab-ci.yml` (Linux) — `pip install -e .` + `requirements-recherche.txt` bloquants,
   gates du registre, suite `test_hyperlab_*`, smoke E2E.
2. `windows-full-nightly.yml` (runner Windows) + `LANCER_HYPERLAB.cmd`.
3. Brancher la collecte **live read-only** (réseau), lancer une session de durée suffisante, clôturer
   `COMPLETE` + hashes, rejouer rapide puis exact, vérifier parité + réconciliation 5 vues, produire le rapport.

Quand ces preuves runtime existent et sont attachées au SHA, le verdict passe à `true` — pas avant.

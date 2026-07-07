# MÉGA-PROMPT CODEX — Finir HyperSmart Observer (Hyperliquid, paper-only, V9)

> Colle ce fichier ENTIER dans le champ *Objectif / Goal* de Codex.
> Maître du projet : `docs/HYPERSMART_FUSION_ROADMAP_V9.md`. Ce prompt = état réel + tout le reste à faire.
> Traite les chantiers **dans l'ordre, un par un**. Après CHAQUE chantier : `python -m pytest -q` vert + mini-preuve chiffrée. Si rouge, corrige AVANT de continuer.

---

## 0. RÈGLES ABSOLUES (sécurité — jamais contourner)
```
PAPER-ONLY · READ-ONLY · DENY-BY-DEFAULT
0 ordre réel · 0 argent réel · 0 clé privée · 0 seed/mnemonic · 0 signature · 0 dépôt/retrait · 0 wallet connect · 0 API privée de trading
execution="forbidden" PARTOUT. Conserver tout assert_paper_only / garde-fou.
AUCUNE démo / donnée synthétique / fabriquée. Pas de données -> état vide honnête. Doute -> NO_TRADE.
Un signal n'est pas un ordre. Un paper-trade n'est pas un ordre. Jamais de promesse de PnL, jamais de chiffres maquillés.
Scraping public + proxy/rotation = AUTORISÉS (AGENTS.md / V9 §8).
Ne pas supprimer le legacy. Ne pas pousser/committer/reset sans demande explicite.
```
Tu es sur Windows : tu PEUX éditer les gros fichiers (`src/hl_observer/ui/routes.py` ~3700 l., `cli.py` ~3000 l.). Edits chirurgicaux + tests ; après, `python -m hl_observer --help` doit marcher.

---

## 1. ÉTAT RÉEL (DÉJÀ FAIT — vérifier, NE PAS refaire)
**Bibliothèque V9 = 100 % (modules purs testés, 84 tests verts) :**
- S0 `runtime_mode`, `storage/run_context`, `config/defaults` · S1 `models/`, `normalization/` (+`reconcile`).
- S2 REST `hyperliquid/rest_info_client` + `collection/{proxy_pool,weight_budgeter,rate_limiter,backoff,circuit_breaker,html_scraper,collect_all,run_collect_all}` · S3 `realtime_monitor/ws_supervisor`.
- S4 `features/{microstructure(CVD/RVOL/VWAP/anchored/impulse/basis/liquidations),orderbook_imbalance,quality_mode,volatility,scan_features}`.
- S5 `scoring/{smart_money_filter,wallet_labels,shortlist_rank}` · copy_fidelity `{exec_quality,tracking_error}`.
- S6 `edge/{edge_calculator,fair_value,signal_decay,copy_degradation,edge_remaining,exit_quality}` · `freshness/freshness_policy` · `signals/{whale_fill_signal,fill_admission,entry_supply_diagnostics,signal_builder,signal_scoring,position_delta_detector}`.
- S7 `risk/*` (var_cvar, loss_halts, adaptive_sizing, circuit_breaker, kill_switch, trade_floor, exec_gates…) · `calibration/{brier,confidence_buckets,model_market,shadow_promote,shadow_runner}`.
- S8 pipeline de décision `copying/simulation_pipeline.run_paper_simulation_decision` (testé) · S9 `backtest/{replay_engine,walk_forward,monte_carlo,runtime_parity,cost_model}`.

**Runtime déjà câblé dans `routes.py` (boucle de copie) :** skip exotiques (`should_skip_exotic_for_copy`), skip backfill (`is_hard_stale_signal`), skip sorties orphelines (`should_skip_orphan_exit_or_unknown`), dédup persistante (`processed_delta_keys` round-trip capé 10k), diagnostics d'entrées fraîches (`fresh_entry_diagnostics`, `filter_diagnostics`).

**Calibration & UX déjà faites :** `LANCER_HYPERSMART.cmd` (ALLOW_ADD_AS_ENTRY=1, MAX_SIGNAL_AGE_MS=30000, MIN_EDGE_BPS=10, SINGLE_WALLET_MIN_EDGE_BPS=15, MIN_LIQUIDITY_SCORE=0.3, MAX_COPY_DEGRADATION_BPS=22). Filtre `markets/universe.is_exotic_market`. Dashboard `simulation_v2.html` anti-saut + badge léger. Lanceur `start_hypersmart_simulation.ps1` lance `run_collect_all` au démarrage (élargit la shortlist).

**Constat live (capture 18:29) :** moteur sain mais **0 entrée** car affamé de signaux frais (≈2 deltas frais / 968k candidats). Bottleneck = OFFRE, pas bruit.

---

## 2. CE QUI RESTE (backlog priorisé — gros du travail)

### R1 — Retirer le code DÉMO / synthétique (viole no-demo) [bloquant éthique]
Commits fautifs `332c055`, `ba6266e`, `6502fab`, `04a6d27` dans `hyper_smart_observer/dydx_v4/`.
- Retirer `_build_demo_wallets()`, `_demo_mode`, `demo_synthetic`, le bypass de gates pour wallets synthétiques (engine.py, live_observer.py, wallet_discovery.py). `dydx_v4/` reste dormant et honnête (échec découverte -> shortlist vide, jamais de wallet inventé).
- **Test** `tests/test_no_demo_wallets.py` ; **DoD** : `grep -rni "demo_synthetic\|_build_demo_wallets\|_demo_mode" hyper_smart_observer src | grep -v test` vide/inerte.

### R2 — ⭐ Converger le chemin de DÉCISION runtime sur le pipeline + modules V9 [le plus important]
Aujourd'hui la boucle `routes.py` score via l'ancien `opportunity_metrics`/`realtime_magic_score`, PAS via les modules V9. Objectif : que le runtime UTILISE la bibliothèque V9.
- Utiliser `signals/fill_admission.admit_live_fill(...)` comme PORTE D'ENTRÉE unique (entrée/sortie/skip + log_decision) en début de boucle, et `fill_identity(...)` pour la dédup persistante (remplacer/renforcer `processed_delta_keys` par une table SQLite `processed_fills`).
- Router les ENTRÉES admises vers `copying/simulation_pipeline.run_paper_simulation_decision(...)` (qui agrège features marché réelles + risk + ordre paper + evidence), au lieu du scorer ad hoc. Réutiliser `edge/edge_calculator`, `edge/fair_value`, `features/scan_features`, `features/microstructure`.
- Conserver le DecisionLedger + evidence-hash. **Aucun edge=-9999** ne doit fuir : si edge non calculable -> NO_TRADE explicite.
- **Tests** : un fill frais BTC propre -> ENTRÉE paper ouverte avec evidence ; un fill exotique/stale/doublon -> skip sans bruit ; parité avec `test_v9_simulation_pipeline_src.py`.
- **DoD** : sur un fixture rejoué, ≥1 entrée paper, 0 bruit (close-sans-position/backfill/doublon/exotique), 0 `-9999` loggé.

### R3 — Exposer le verdict OFFRE vs GATES au dashboard (T8)
- Brancher `signals/entry_supply_diagnostics.build_entry_supply_report(...)` sur les compteurs `fresh_entry_diagnostics`/`filter_diagnostics` et publier le verdict (`SUPPLY` / `GATES` / `OK` / `NO_DATA`) + `next_action` dans `/api/simulation/status` (petit module `status_routes.py`) et l'afficher dans `simulation_v2.html` (panneau « État du scan »).
- **DoD** : le dashboard dit explicitement « blocage = offre (élargir wallets) » ou « blocage = gates (calibrer) ».

### R4 — Augmenter l'OFFRE de signaux d'entrée frais (le vrai déblocage du 0-position)
- Utiliser `scoring/shortlist_rank.rank_shortlist(...)` pour prioriser les leaders les + actifs/qualité dans la shortlist bornée.
- Activer/garantir **WS userFills** sur les 10 leaders chauds (cap 10 users) pour capter les fills frais en intra-poll, pas seulement les diffs de snapshots REST.
- Boucler `run_collect_all` périodiquement (pas qu'au démarrage) pour empiler des leaders. Exposer « wallets suivis » et « deltas frais/min » au dashboard.
- **DoD** : sur une vraie session, « deltas frais » >> 2 ; sinon afficher honnêtement l'insuffisance d'offre (jamais forcer).

### R5 — Sorties paper + PnL réalisé
- Quand un leader REDUCE/CLOSE une position qu'on DÉTIENT en paper : simuler la sortie (prix réel courant), calculer le PnL réalisé, mettre à jour l'équité, écrire un évènement lifecycle CLOSE/REDUCE. Vérifier PnL long ET short corrects, frais non doublés.
- **Tests** : `test_pnl_long_correct`, `test_pnl_short_correct`, `test_fees_not_double_counted`, lifecycle OPEN/ADD/REDUCE/CLOSE.

### R6 — Calibration en runtime (Brier / shadow→primary)
- Enregistrer, pour chaque décision acceptée, la proba prédite et le résultat observé ; alimenter `calibration/shadow_runner.ShadowCalibrationRunner` (shadow n'agit jamais) ; exposer le Brier + l'avantage shadow au dashboard/recherche. Promotion uniquement via `ready_for_promotion`.

### R7 — Backtest / replay / parité + tests obligatoires
- Brancher `backtest/replay_engine` + `runtime_parity` sur le pipeline V9 ; garantir la séparation stricte LIVE/BACKTEST/REPLAY/TEST_FIXTURE (jamais mélanger les PnL via `storage/run_context`).
- Couvrir les 16 tests obligatoires V9 (§4 roadmap) : REST mock, WS mock, reconnect, gap recovery, dedupe, pagination, lifecycle, stale refusé, edge faible refusé, liquidité faible refusée, PnL long/short, fees non doublés, séparation contexts, dashboard read-only, config safe, 0 ordre réel.

### R8 — ⭐ PREUVE end-to-end (obligatoire, anti-bullshit)
- Lancer une vraie session courte read-only paper (vraies données Hyperliquid) OU rejouer le dernier ledger via le replay.
- Fournir AVANT/APRÈS chiffrés : nb décisions, **entrées paper (>0 attendu)**, répartition des refus (le bruit doit s'effondrer), 0 coin exotique, 0 âge > 60 s, 0 doublon, verdict offre/gates.
- **Interdit** : forcer des entrées / inventer des données. Si 0 signal propre sur la fenêtre, l'afficher honnêtement.

### R9 — Continuer les slices V9 restantes
- Compléter ce qui manque encore dans `docs/HYPERSMART_FUSION_ROADMAP_V9.md` §3/§6 (modules + tests + DoD), sans dupliquer l'existant (vérifier d'abord avec un scan de couverture).

---

## 3. CONTRAINTES TESTS
- `python -m pytest -q` doit rester vert à chaque étape. Ne jamais déclarer « fait » avec des tests rouges.
- Si un test échoue à cause d'un module ancien/WIP non lié, le documenter précisément, ne pas masquer.

## 4. RAPPORT FINAL (français, obligatoire)
1. Fichiers modifiés/créés. 2. Pour chaque R fait : preuve chiffrée AVANT/APRÈS. 3. Tests lancés (résumé `X passed`). 4. Limites restantes + prochaines slices. 5. **Confirmation sécurité** : `0 ordre réel · 0 argent · 0 clé · 0 signature · 0 dépôt/retrait · 0 démo`.

**Definition of Done globale** : sur une vraie session courte, le ledger montre **au moins quelques entrées paper sur des perps crypto liquides**, le bruit a disparu, le dashboard dit où est le blocage, tous les tests passent, et la simulation reste 100 % paper/read-only.

## 5. NOTES
- Le module `signals/fill_admission.py` est PRÊT : `admit_live_fill(action_type, coin, fill_ts_ms, now_ms, already_seen, has_matching_paper_position, leader_price, config=FillAdmissionConfig(...))` → `.admit/.kind(ENTRY|EXIT|SKIP)/.reason/.log_decision`. C'est la porte d'entrée à brancher en R2.
- Ne réécris pas les modules V9 existants : importe-les. Ajoute les fonctionnalités via petits modules + edits chirurgicaux.

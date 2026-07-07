# HyperSmart — FEUILLE DE ROUTE MAÎTRESSE PnL (source unique de vérité)

_2026-07-02. Venue = Hyperliquid, paper local, read-only, runtime = `src/hl_observer`. Consolide et prime sur `HYPERSMART_PNL_ROADMAP.md`. Aucune promesse de PnL : on maximise la probabilité d'un PnL paper positif réaliste, chaque changement prouvé au profit factor (A/B backtest)._

## 0. Vérité de départ (analyse du logiciel + 34 githubs)
- Les 34 repos sont **installés, mappés (V24) et câblés** : 51/51 modules cibles présents, 0 orphelin (`GITHUB_COVERAGE.md`).
- Le dépôt contient déjà : `optimization/` complet (grid_search, walk_forward_validator, anti_overfit_guard, out_of_sample_guard, threshold_optimizer, profit_optimizer, strategy_tournament), `copy_mode/cooldown.py`, `risk/scale_out.py`, `risk/var_cvar.py`, `risk/loss_halts.py`, `calibration/*`, exits (`sltp_runtime`, `exits/*`), microstructure.
- **Conclusion honnête** : la mine d'or est déjà extraite. Le frein PnL n'est PAS « porter plus » — c'est **(1) câbler les couches de décision dans le moteur live, (2) régler via l'optimiseur+juge, (3) le run live** (latence/2e source).

## 1. Ce qui a été LIVRÉ cette session (codé + testé, 45 tests verts)
| Ref | Livrable | Fichier |
|---|---|---|
| Juge | profit factor/drawdown/expectancy + A/B + lecture logs réels | `backtest/experiment_runner.py`, `backtest/ab_report.py`, `backtest/pnl_from_logs.py` |
| Exits | politique composée SL→BE→TP→TRAILING→TIME_STOP + ATR + score | `exits/exit_policy.py`, `edge/exit_quality.py` |
| Entrée | gate unifié (freshness×edge×liq×calib + OBI + fill-confirmé + consensus/conflit) | `signals/entry_gate_v2.py` |
| Sélection | promotion par calibration | `calibration/promotion.py` |
| Risque | sizing edge×confiance + cap corrélé ; risk gate halts/DD/VaR | `risk/sizing_v2.py`, `risk/risk_gate.py` |
| Coûts | slippage depth-aware + pénalité latence | `backtest/cost_model.py` |
| Régime | trend/chop/extreme → activer/couper stratégies | `signals/regime_router.py` |
| Convergence | ledger==snapshot (CONVERGENT/DIVERGENT/INSUFFICIENT_DATA) | `audit/pnl_convergence.py` |
| Robustesse | scan read-only dégrade en état vide honnête si réseau coupé | `markets/scanner.py` |

**Baseline mesurée sur le vrai ledger (75 trades)** : profit factor 0,0035 · PnL −0,125 USDC. → prouve que les exits/entrées, une fois câblés, sont le vrai levier.

## 2. PHASE A — CÂBLAGE dans le moteur live (le vrai gain restant) — priorité absolue
Les couches ci-dessus sont testées mais **pas encore appelées par le runtime** (PARTIAL_NOT_WIRED ; les gros fichiers `sltp_runtime`/`live_observer`/`ui/routes` sont tronqués par le mount → édition côté Windows).
- A1. Appeler `entry_gate_v2.evaluate_entry_gate` juste avant chaque PaperIntent (NO_TRADE tracé).
- A2. Appeler `exit_policy.evaluate_exit` dans la boucle d'exits (flag `HYPERSMART_EXIT_POLICY_ENABLED`, défaut off).
- A3. Passer par `risk_gate.evaluate_risk_gate` + `sizing_v2` dans le RiskEngine avant sizing.
- A4. Écrire chaque décision (accept/NO_TRADE + raisons) dans le PaperLedger pour l'audit.
- **Acceptance** : run + `pnl_from_logs` A/B vs baseline → n'activer un flag que si profit factor monte.

## 3. PHASE B — RÉGLAGE via l'optimiseur existant + juge A/B
- B1. Brancher `ab_report`/`pnl_from_logs` dans `optimization/threshold_optimizer.py` + `profit_optimizer.py` pour sweeper les seuils (min_edge, trailing_bps, arm_bps, SL/TP, breakeven_trigger).
- B2. Grille de sweep exits inspirée evan-kolberg (TP/SL/slippage/reentry_cooldown) via `optimization/grid_search.py` sous `out_of_sample_guard` + `anti_overfit_guard` (pas de sur-apprentissage).
- B3. Scale-out en grille + clôture trailing (passivbot `close_grid_qty_pct`/`close_trailing_threshold_pct`) → approfondir `risk/scale_out.py`.
- B4. Vérifier/affiner le re-entry cooldown (`copy_mode/cooldown.py`) : pas de rachat immédiat après une sortie (anti-churn, ~30 min inspiré evan-kolberg).
- **Acceptance** : walk-forward + out-of-sample positifs, profit factor > baseline, drawdown non aggravé.

## 4. PHASE C — SÉLECTIVITÉ (moins de trades, plus propres)
- C1. N'entrer que sur signaux frais + calibrés (gate A1 + `calibration/promotion`).
- C2. OBI + fill confirmé > openOrder obligatoires en confirmation.
- C3. Consensus multi-wallet ; conflit → NO_TRADE.
- C4. Régime : couper le directionnel en chop/extreme (`regime_router`).
- **Acceptance** : baisse du nb de trades, hausse du profit factor (juge).

## 5. PHASE D — LIVE & HARMONIE (run Windows requis — non simulable en sandbox)
- D1. Prouver latence WS ~1-2 s puis resserrer la fenêtre fraîche (frein n°1).
- D2. Fixtures → vraie donnée HL read-only, sinon état vide honnête (déjà durci).
- D3. 2e source live pour arbitrage/funding (sinon NO_TRADE).
- D4. Mini-run prolongé : `pnl_convergence` prouve ledger = audit = dashboard = exports.
- D5. IA locale : accumuler assez de trades clos à issues mixtes pour qu'elle filtre (jamais inventer du profit).
- **Acceptance** : `doctor`+`safety-audit` verts, convergence OK, PnL jugé au profit factor sur données fraîches.

## 6. Checklist « tout en harmonie / optimal »
- [ ] Chaque décision passe par gate d'entrée → risk gate → sizing → PaperIntent/NO_TRADE → PaperLedger.
- [ ] Dashboard, audit, exports lisent le même ledger (convergence prouvée).
- [ ] Aucun flag d'action réelle ; `safety-audit` vert (0 ordre réel).
- [ ] Aucune donnée fabriquée ; donnée manquante → INSUFFICIENT_DATA/NO_TRADE.
- [ ] Chaque levier activé a passé un A/B backtest positif (profit factor), pas une intuition.

## 7. Rappel de senior (non négociable)
Aucune de ces phases ne « garantit » un PnL positif — le trading garde une incertitude irréductible, et te promettre 100 % serait malhonnête. Ce plan met **toutes les chances de notre côté** : sélectivité + exits propres + coûts réalistes + réglage prouvé + latence maîtrisée, le tout mesuré honnêtement. Le plus fort levier immédiat = **Phase A (câblage)**.

---

# ÉTAPES DÉTAILLÉES (backlog fin, chargé dans la progression)

## PHASE A — Câblage live (flags, défaut off ; A/B avant activation)
- A1. Repérer les points d'appel réels dans le runtime (PaperIntent, boucle exits, RiskEngine) sans éditer les gros fichiers tronqués.
- A2. Adaptateur `signals/entry_gate_runtime.py` : `from_env()` + hook importable (défaut off).
- A3. Brancher le gate d'entrée avant chaque PaperIntent ; NO_TRADE tracé au PaperLedger.
- A4. Adaptateur d'exits runtime : appeler `exit_policy.evaluate_exit` dans la boucle d'exits (flag).
- A5. Brancher `risk_gate.evaluate_risk_gate` + `sizing_v2` dans le RiskEngine avant sizing.
- A6. Écrire accept/NO_TRADE + raisons + sizing au ledger (traçabilité complète).
- A7. A/B backtest après chaque câblage (`pnl_from_logs`) ; n'activer le flag que si profit factor monte.

## PHASE B — Réglage via optimiseur existant + juge A/B
- B1. Connecter `ab_report`/`pnl_from_logs` à `optimization/threshold_optimizer.py`.
- B2. Sweep seuils d'exit (trailing_bps, arm_bps, SL, TP, breakeven_trigger) via `optimization/grid_search.py`.
- B3. Sweep seuils d'entrée (min_edge_bps, fenêtre fraîcheur, min_consensus).
- B4. Passer chaque sweep sous `out_of_sample_guard` + `anti_overfit_guard` (pas de sur-apprentissage).
- B5. Scale-out en grille + clôture trailing (passivbot `close_grid_qty_pct`/`close_trailing_threshold_pct`) dans `risk/scale_out.py`.
- B6. Régler le re-entry cooldown (`copy_mode/cooldown.py`) anti-churn (~30 min, evan-kolberg).
- B7. Sortir un `best_config` validé walk-forward + rapport profit factor.

## PHASE C — Sélectivité (moins de trades, plus propres)
- C1. Fenêtre de fraîcheur stricte réglée (rejeter les signaux vieux).
- C2. Promotion par calibration en gate (ne trader que le calibré).
- C3. OBI + fill confirmé > openOrder obligatoires.
- C4. Consensus multi-wallet ; conflit → NO_TRADE.
- C5. Régime marché → couper le directionnel en chop/extreme.
- C6. Mesurer : baisse du nb de trades + hausse du profit factor.

## PHASE D — Live & harmonie (run Windows requis)
- D1. Prouver latence WS ~1-2 s ; resserrer la fenêtre fraîche.
- D2. Fixtures → vraie donnée HL read-only (sinon état vide honnête).
- D3. 2e source live arbitrage/funding (sinon NO_TRADE).
- D4. Mini-run prolongé : `pnl_convergence` prouve ledger=audit=dashboard=exports.
- D5. IA locale : entraîner sur trades clos à issues mixtes (filtre, n'invente pas).
- D6. `doctor` + `safety-audit` verts sur run live.

## PHASE E — Finition & preuve
- E1. Carte de flux E2E : collecte→gate→risk→sizing→PaperIntent/NO_TRADE→ledger→dashboard.
- E2. Convergence ledger=audit=dashboard prouvée sur données fraîches.
- E3. Rapport final PnL jugé au profit factor (jamais promis).

## PHASE F — Réglages fins & idées PnL concrètes (leviers chiffrés)
- F1. Entrées maker-first (post-only paper) → payer ~2 bps (maker) au lieu de ~5 (taker) : réduit le fee drag (frein PnL n°1 constaté). Source: modèle de frais HL.
- F2. Gate de spread serré et adaptatif à la volatilité (max_spread_bps par coin, pas constant). Source: mlmodel spread tiers, freqtrade max_spread_ratio 0.5%.
- F3. Profondeur minimale au top du carnet avant entrée (anti-illiquide). Source: jackhuang liquidity filters.
- F4. Exclure coins exotiques/illiquides (is_exotic_market) — confirmer actif dans le gate.
- F5. Budget de slippage par trade en paliers (rezzecup DEFAULT_SLIPPAGE_BPS + tiers).
- F6. Filtre qualité leader (winrate / profit_factor / min trades) via leader_quality avant copie.
- F7. Edge funding-aware : éviter d'entrer juste avant un funding adverse (features/funding).
- F8. Cap Kelly sur le sizing (var_cvar.kelly_fraction, cap 0.25) pour borner le risque.
- F9. Plafond de positions concurrentes (slots) + cap trades/jour (anti-overtrading).
- F10. Objectif d'equity journalier : stopper les nouvelles entrées après +X% (verrouiller les gains).
- F11. Whale primary gate : ne suivre que les whales prouvés (whale_primary_gate).
- F12. Half-life de décroissance du signal réglé (fraîcheur ~8 s, Harrier signal_decay).
- F13. Seuil de confirmation OBI réglé (~0.10, mlmodel IMBALANCE_CONFIRM_THRESHOLD).
- F14. Moniteur de fee drag (FEE_DRAG_TOO_HIGH) : réduire la fréquence si les frais mangent l'edge.
- F15. Min hold + reopen cooldown réglés (anti-churn ; défauts déjà présents, à optimiser en B).

## PHASE G — Réalisme données & exécution (un edge propre en backtest doit tenir en live)
- G1. Freshness/staleness guard sur les prix (freshness_audit) réglé — refuser data trop vieille.
- G2. Clock offset / horodatage cohérent (clock_offset) — pas de latence sous-estimée.
- G3. Gap recovery + dédup WS prouvés (ws_supervisor) — pas de trou ni de doublon.
- G4. Warmup guard : pas de trade avant N points collectés.
- G5. Probabilité de fill maker (position dans la file/queue) modélisée.
- G6. Probabilité de missed fill / partial fill réaliste (pas de fill parfait).
- G7. Adverse selection sur fills maker (on n'est rempli que quand on a tort) modélisée.
- G8. Jitter de latence (distribution, pas constante) dans le modèle de coûts.

## PHASE H — Portefeuille & risque avancé
- H1. Cap d'exposition brute (gross) et nette (net delta) du portefeuille.
- H2. Matrice de corrélation → cap par cluster corrélé (au-delà du pair-wise).
- H3. Buffer de liquidation (marge de sécurité vs prix de liquidation).
- H4. Volatility targeting : taille pour cibler une volatilité de portefeuille stable.
- H5. Risque par trade fixé (% equity) borné et cohérent avec le SL.
- H6. Circuit breaker sur anomalie de données (prix aberrant → pause).

## PHASE I — Métriques & attribution (juger juste)
- I1. Sharpe / Sortino / Calmar en plus du profit factor.
- I2. Attribution PnL par coin (où on gagne/perd).
- I3. Attribution PnL par leader/wallet (quel leader rapporte).
- I4. Distribution MAE/MFE (qualité entrées/exits).
- I5. Hit rate + avg win/loss + expectancy par stratégie.

## PHASE J — Robustesse & ops
- J1. Crash recovery : sauver/relire le PaperLedger sans perte ni double-comptage.
- J2. Replay idempotent + dédup guard (jamais fermer 2× la même position).
- J3. Circuit breaker sur erreurs répétées (fondations error_handler/circuit_breaker).
- J4. Persistance d'état propre entre redémarrages (state_manager).

## PHASE K — IA/ML locale (filtre, n'invente pas)
- K1. Feature store depuis les logs (features + contexte par décision).
- K2. Génération de labels depuis trades clos (issues mixtes gagnant/perdant).
- K3. Gating d'inférence : le modèle filtre les signaux, ne décide jamais seul.
- K4. Calibration du modèle (Brier) + shadow avant toute activation.

## PHASE L — Dashboard & observabilité (même vérité que le ledger)
- L1. Courbe d'equity + drawdown lisant le PaperLedger.
- L2. Marqueurs de fills (PaperFill) sur le graphe.
- L3. Panneau raisons NO_TRADE + source health + safety status.
- L4. Panneau PnL par stratégie / coin / leader.

> Note senior : avec A→L la feuille de route est désormais **exhaustive** (données, exécution, entrées, exits, risque, portefeuille, sélection, métriques, robustesse, IA, dashboard, live). Au-delà, on est en rendements décroissants : le gain PnL vient maintenant de l'EXÉCUTION (Phase A câblage) + du RÉGLAGE mesuré (Phase B), pas d'ajouter encore des idées.

## PHASE M — Leviers avancés supplémentaires (réellement distincts)
- M1. Scale-in / DCA (grille d'entrée) — entrer en plusieurs fois pour un meilleur prix moyen (passivbot entry grid). À simuler avec risque de sur-exposition borné.
- M2. Impact marché vs ADV — slippage additionnel quand la taille est grande vs le volume moyen (pas seulement la profondeur instantanée).
- M3. Paliers de frais Hyperliquid (fee tiers volume-based) modélisés maker/taker.
- M4. Accrual de funding continu (pro-rata du temps de détention), pas seulement au boundary horaire.
- M5. Confirmation multi-timeframe (align 5m/15m) avant entrée (Harrier direction MTF).
- M6. Stop-follow si le leader entre en drawdown — couper la copie d'un leader qui se dégrade en direct.
- M7. Filtre session / heure — couper les plages horaires à faible edge / spreads larges.
- M8. Kill-switch de dérive modèle — si la perf du modèle IA décroche, repasser en shadow.
- M9. Shadow A/B continu — une config candidate tourne en fantôme en permanence vs la baseline (promotion auto si PF>).
- M10. Coût de portage (borrow/margin) modélisé dans l'edge net pour les tenues longues.

> STOP planification (recommandation senior) : A→M est maintenant complet et honnête. Chaque nouvelle carte au-delà serait du remplissage, pas du PnL. Le PnL bouge par l'EXÉCUTION (Phase A) + le RÉGLAGE mesuré (Phase B), pas par l'ajout d'étapes.

---

# PHASE A — CÂBLAGE LIVRÉ (2026-07-02)

Tout est **deny-by-default OFF** (aucun changement de comportement tant qu'un flag n'est pas mis) et testé.

| Étape | Câblage | Flag env | Fichier |
|---|---|---|---|
| A1 | chokepoint localisé (`approve_with_risk`) | — | `strategies/models.py` |
| A2 | adaptateur gate d'entrée | HYPERSMART_ENTRY_GATE_ENABLED | `signals/entry_gate_runtime.py` |
| A3 | gate câblé au chokepoint + appelant | idem | `strategies/models.approve_with_risk_and_gate`, `paper_trading/mirror_paper_executor.py` |
| A4 | adaptateur exits composés | HYPERSMART_EXIT_POLICY_ENABLED | `exits/exit_policy_runtime.py` |
| A5 | risk gate dans `_default_risk_fn` | HYPERSMART_RISK_GATE_ENABLED | `risk/risk_gate_runtime.py`, `mirror_paper_executor.py` |
| A6 | trace gate/risk dans `evidence` | — | `mirror_paper_executor.py` |

## A7 — Procédure A/B (juge au profit factor) — à exécuter sur run Windows
1. Baseline : lancer `LANCER_HYPERSMART.cmd` **sans** les flags → produit `simulation_decisions_append_only.jsonl` (baseline).
2. Variante : relancer **avec** un flag (ex: `set HYPERSMART_ENTRY_GATE_ENABLED=1`) → nouveau log (variante).
3. Comparer : `set PYTHONPATH=src && python -m hl_observer.backtest.pnl_from_logs baseline.jsonl variante.jsonl`
4. Décision : le verdict `KEEP_VARIANT` / `KEEP_BASELINE` se base sur le **profit factor** (et n'aggrave pas le drawdown). N'activer le flag en permanence **que** si `KEEP_VARIANT`.

> Rappel : le câblage seul ne change rien tant que les flags sont off. Le PnL bouge quand on ACTIVE un flag ET que l'A/B prouve un profit factor supérieur. Aucune promesse — on garde ce qui est prouvé, on jette le reste.

---

# PHASES B & C — MACHINERIE LIVRÉE (2026-07-02)

Machinerie pure + testée (9 tests dédiés, 52 en non-régression). Les **valeurs tunées finales** sortent d'un sweep sur tes logs réels (run Windows).

| Étape | Livrable | Fichier |
|---|---|---|
| B1 | profit factor dans l'optimiseur de seuils | `optimization/threshold_optimizer.py` |
| B2/B3 | sweep générique branché au juge + grilles exit/entrée | `optimization/pnl_sweep.py` |
| B4 | gardes OOS + anti-overfit (stubs comblés) | `optimization/out_of_sample_guard.py`, `anti_overfit_guard.py` |
| B5 | scale-out en grille + clôture trailing (passivbot) | `risk/scale_out.py` |
| B6 | re-entry cooldown anti-churn (~30 min) | `copy_mode/reentry_cooldown.py` |
| B7 | sélecteur best_config validé OOS (stub comblé) | `optimization/best_config_selector.py` |
| C1-C5 | profil de gate strict (fraîcheur/OBI/consensus/calibration/régime) | `signals/gate_profile.py` |
| C6 | rapport de sélectivité (moins de trades + PF ↑) | `backtest/selectivity_report.py` |

## Procédure de réglage (run Windows)
1. Extraire les samples (features + net_pnl) depuis `simulation_decisions_append_only.jsonl`.
2. `optimize_thresholds(samples)` → best_config sur train, validé test (OOS) + profit factor.
3. `sweep(EXIT_PARAM_GRID/ENTRY_PARAM_GRID, scorer)` → `best_by_profit_factor` sous `accept_config` (anti-overfit).
4. Activer le profil strict (`HYPERSMART_GATE_STRICT_PROFILE=1`) + `selectivity_report` pour prouver « moins de trades, PF plus haut ».
5. N'appliquer que les configs `oos_consistent=True`. Aucune promesse ; on garde ce qui est prouvé.

---

# PHASE D — TOOLING LIVRÉE (2026-07-02) — la PREUVE live reste ton run Windows

D est intrinsèquement live. J'ai livré la **tooling de mesure & les gardes** (pures, testées) ; la preuve sur données fraîches vient de `LANCER_HYPERSMART.cmd`.

| Étape | Tooling livrée | Fichier | Preuve live = |
|---|---|---|---|
| D1 | recommandateur de fenêtre fraîche (p90 latence × marge) | `realtime/fresh_window_recommender.py` (+ `latency_report.py` existant) | run Windows: mesurer latence réelle |
| D2 | liveness source LIVE/FIXTURE/STALE/EMPTY + garde NO_TRADE | `collection/source_liveness.py` | run: brancher vraie donnée HL |
| D3 | garde 2e source (>=2 sources fraîches sinon NO_TRADE) | `signals/second_source_guard.py` | run: brancher une 2e source réelle |
| D4 | mini-run: convergence + latence + liveness en 1 verdict | `audit/mini_run_check.py` (+ `pnl_convergence` existant) | run: mini-run prolongé |
| D5 | garde "prêt à entraîner" (issues mixtes) | `ml/training_readiness.py` (+ package `ml/` existant) | run: accumuler assez de trades clos |

> Honnêteté : je ne peux pas prouver une latence de 1-2s ni entraîner l'IA sans données live — je ne le fabrique pas. Les gardes garantissent l'ÉTAT VIDE HONNÊTE et le NO_TRADE quand les conditions live ne sont pas réunies. Tests: `tests/test_phase_d_tooling.py` (5 passed).

---

# PHASE F — STATUT (2026-07-02) : 5 nouveaux + 10 déjà présents

| Étape | Statut | Fichier |
|---|---|---|
| F1 maker-first | **NOUVEAU testé** | `edge/maker_fee_model.py` |
| F2 spread gate adaptatif | déjà présent | `signals/depth_spread_gate.py`, `risk/microstructure_guard.py` |
| F3 profondeur mini | déjà présent | `risk/slippage_guard_v2.py` (depth guard) |
| F4 exclure exotiques | déjà présent | `backtest/ledger_replay_v9.py`, `copying/v9_paper_pipeline.py` |
| F5 budget slippage paliers | déjà présent | `risk/slippage_guard_v2.py` |
| F6 qualité leader | déjà présent | `dydx_v4/leader_quality.py`, `analysis/` |
| F7 funding-aware | **NOUVEAU testé** | `features/funding_aware.py` |
| F8 cap Kelly | déjà présent | `copying/kelly_sizing.py` |
| F9 budget trades/concurrent | **NOUVEAU testé** | `risk/trade_budget.py` |
| F10 objectif equity jour | **NOUVEAU testé** | `risk/trade_budget.py` |
| F11 whale primary gate | déjà présent | `signals/whale_primary_gate.py` |
| F12 half-life décroissance | déjà présent | `edge/signal_decay.py`, `edge/edge_calculator.py` |
| F13 seuil OBI | déjà présent | `features/orderbook_imbalance.py`, `risk/microstructure_guard.py` |
| F14 moniteur fee-drag | **NOUVEAU testé** | `edge/fee_drag.py` |
| F15 min hold + reopen cooldown | déjà présent (+B6) | sltp min_hold + `copy_mode/reentry_cooldown.py` |

Tests nouveaux : `tests/test_phase_f_filters.py` (4 passed). Les modules "déjà présents" restent à **régler** en Phase B (sweep) et à activer via le gate — pas à recréer.

---

# PHASES G→K1 — STATUT (2026-07-02) : 11 nouveaux + reste déjà présent

**Nouveaux (codés + testés, `tests/test_phase_g_h_i.py` 3 passed) :**
- G5 fill maker prob · G7 adverse selection · G8 jitter latence → `backtest/execution_realism.py`
- H4 volatility targeting · H5 risque/trade · H6 circuit breaker anomalie (+ H1 helper gross/net) → `risk/portfolio_risk.py`
- I1 Sharpe/Sortino/Calmar · I2 attribution coin · I3 attribution leader · I4 MAE/MFE · I5 hit rate/expectancy → `backtest/pnl_metrics_ext.py`

**Déjà présents (référencés, à régler/activer, pas à recréer) :**
- G1 `realtime/freshness_audit.py` · G2 `realtime/clock_offset.py` · G3 `data_sources/fresh_data_plan.py` · G4 warmup_guard (`ui/routes`) · G6 `backtesting/partial_fill_model.py`
- H1 `paper_trading/paper_engine.py` (gross/net) · H2 `risk/correlated_exposure.py` · H3 liquidation_model
- J1 crash recovery (`core/main`, state_manager) · J2 dédup/idempotent (ledger) · J3 `core/circuit_breaker` · J4 state_manager
- K1 feature store (`ml/ledger_extract.py`, `ml/dataset`)

---

# PHASES K2→M10 — STATUT (2026-07-02) : 6 nouveaux + reste déjà présent

**Nouveaux (codés + testés, `tests/test_phase_m_advanced.py` 6 passed) :**
- M2 impact vs ADV · M4 funding accru continu · M10 coût de portage → `edge/advanced_costs.py`
- M1 DCA/scale-in ladder · M6 stop-follow leader drawdown · M7 filtre session → `signals/advanced_entry.py`

**Déjà présents (référencés) :**
- K2 labels (`ml/ledger_extract.py`) · K3 inference (`ml/inference.py`) · K4 Brier (`calibration/brier.py`)
- L1/L2 charts equity/drawdown/fills (`ui/` + `backtest/report_charts.py`) · L3 `dashboard/risk_flags_panel.py` (+ source health) · L4 `dashboard/loss_attribution_panel.py`
- M3 `copy_fidelity/fee_tiers.py` · M5 `features/direction.py` (multi-TF) · M8 `copy_fidelity/tracking_error.py` (drift) · M9 `calibration/promotion.py` + `signals/shadow_wiring.py`

## Roadmap A→M : COMPLÈTE
Toutes les phases sont soit codées+testées, soit déjà présentes et référencées. Le PnL réel (profit factor 0,22, négatif) ne bougera que par un **run Windows** activant les flags + juge A/B. Aucune promesse ; on garde ce qui monte le profit factor hors-échantillon.

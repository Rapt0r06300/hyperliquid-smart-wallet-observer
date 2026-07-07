# HyperSmart — Feuille de route PnL (par levier, pas par repo)

_2026-07-02. Venue = Hyperliquid, paper local, read-only. Cible = `src/hl_observer`. Aucune promesse de PnL : on maximise la probabilité d'un PnL paper positif réaliste, chaque changement validé en backtest avant activation._

## Principe
Les 34 repos sont déjà mappés (V24) et 51/51 modules cibles sont câblés (`GITHUB_COVERAGE.md`). Le problème n'est donc PAS « porter plus de repos » — c'est **approfondir les modules qui pilotent le PnL** et **prouver leur gain en backtest**. Un module câblé mais superficiel (ex: `exit_quality.py` = 11 l.) ne rapporte rien.

Règle dure : chaque idée passe par DecisionEngine/RiskEngine → PaperIntent ou NO_TRADE → PaperLedger. Aucune ne bypasse l'edge net ni le no-real-trade. Aucune activation sans backtest.

## Statut de profondeur (sondé le 2026-07-02)
| Module cible (src/hl_observer) | Lignes | Profondeur |
|---|---|---|
| paper_trading/sltp_runtime.py | 329 | SOLIDE |
| features/microstructure.py | 192 | SOLIDE |
| features/orderbook_imbalance.py | 118 | OK |
| edge/edge_net_v12.py | 115 | OK |
| edge/fair_value.py | 103 | OK |
| risk/var_cvar.py | 89 | OK |
| risk/loss_halts.py | 86 | OK |
| calibration/confidence_buckets.py | 67 | OK |
| calibration/brier.py | 63 | OK |
| backtest/no_lookahead_guard.py | 62 | OK |
| risk/adaptive_sizing.py | 64 | OK |
| scoring/smart_money_filter.py | 63 | OK |
| backtest/experiment_runner.py | 56 | MOYEN |
| features/funding.py | 51 | SUPERFICIEL |
| funding/*.py | 26-29 | SUPERFICIEL |
| signals/entry_quality_gate.py | 31 | MINCE |
| **edge/exit_quality.py** | **11** | **STUB — trou PnL n°1** |

## Leviers de PnL (ordre = impact décroissant)

### LEVER A — Exits (le n°1 du PnL réalisé)  ▶ P0
- Sources : tony-42069 (SL/TP/trailing), freqtrade (trailing_stop_positive 0.5%, stoploss -10%), harrier (TP50/SL30).
- Cible : `paper_trading/sltp_runtime.py` (solide) + **`edge/exit_quality.py` (STUB à approfondir)**.
- Action : implémenter un vrai scoring de qualité d'exit (MFE/MAE, temps-en-profit, exit vs mark) + trailing discipliné paramétrable ; brancher dans sltp_runtime.
- Mécanisme PnL : coupe les pertes tôt, laisse courir les gains — la cause racine des pertes passées (exits synthétiques sur entrées tardives) est ici.
- Validation : backtest A/B (trailing on/off) sur logs réels ; juger au **profit factor**.

### LEVER B — Fraîcheur du signal  ▶ P0 (déjà solide, à garder autoritaire)
- Sources : Harrier (signal decay), interne `freshness/`.
- Cible : `freshness/signal_decay.py`, gate d'admission.
- Action : garder la fenêtre fraîche stricte ; ne jamais entrer sur signal vieux (déjà `STALE_SIGNAL`).
- Mécanisme : les entrées fraîches ont l'edge ; les tardives paient le spread sans l'edge.

### LEVER C — Gate d'entrée edge-net après coûts  ▶ P0 (présent, à consolider)
- Sources : gajesh (min edge), rustjesty (min_profit_usd), ramilexe (opportunity %).
- Cible : `edge/edge_net_v12.py` + `edge/edge_remaining.py` + `signals/entry_quality_gate.py` (MINCE).
- Action : approfondir entry_quality_gate (composer freshness × edge_net × liquidité × calibration en un verdict unique et tracé). Plancher net 30 bps + plancher USD déjà en place.
- Mécanisme : moins de trades, plus propres. Profit factor > 1 même à winrate 30-40%.

### LEVER D — Sizing & budget de risque  ▶ P1
- Sources : MrFadiAi (adaptive sizing, halts jour/mois), passivbot (exposure limits), CloddsBot (VaR/CVaR).
- Cible : `risk/adaptive_sizing.py`, `risk/correlated_exposure.py`, `risk/var_cvar.py`, `risk/loss_halts.py`.
- Action : sizing proportionnel à l'edge net et à la confiance calibrée ; halts drawdown ; cap corrélé (pas 10 positions ETH-corrélées).
- Mécanisme : protège l'equity, réduit la variance → PnL plus régulier.

### LEVER E — Réalisme des coûts (fees/spread/slippage/depth/latence)  ▶ P1
- Sources : rustjesty (depth average price), jackhuang (fees/slippage/liquidity filters), ArbiBot (latence pénalise l'edge).
- Cible : `features/basis.py`, `features/orderbook_imbalance.py`, `edge` cost model.
- Action : slippage dérivé de la profondeur réelle du carnet (pas constante) ; pénalité latence sur l'edge.
- Mécanisme : un edge « propre » en backtest qui tient en live = pas de PnL fantôme.

### LEVER F — Calibration & promotion  ▶ P1
- Sources : CloddsBot (confidence buckets), evan-kolberg (Brier).
- Cible : `calibration/confidence_buckets.py`, `calibration/brier.py`.
- Action : ne trader que les buckets de confiance calibrés (Brier bas) ; shadow-promote les autres.
- Mécanisme : filtre les faux signaux → augmente le profit factor.

### LEVER G — Funding / basis / arbitrage (secondaire tant que pas de 2e source live)  ▶ P2
- Sources : gajesh (spike 2σ, drawdown kill), rustjesty (delta-neutral, partial-fill guard), Drakkar (triangulaire).
- Cible : `funding/*` (SUPERFICIEL), `features/funding.py`, `arbitrage/`.
- Action : approfondir SEULEMENT quand une 2e source réelle est branchée ; sinon état vide honnête.
- Mécanisme : edge additionnel décorrélé du copy — mais inutile sur fixtures.

### LEVER H — Porte de validation backtest (transverse, PRÉREQUIS de tout)  ▶ P0
- Sources : freqtrade (no-lookahead, recursive), evan-kolberg (ledger/book replay, experiment runner).
- Cible : `backtest/no_lookahead_guard.py`, `backtest/experiment_runner.py` (MOYEN → renforcer).
- Action : rendre l'experiment_runner capable de comparer A/B chaque levier sur logs réels et sortir profit factor + drawdown.
- Mécanisme : sans ça, tout « gain PnL » est une croyance. C'est le juge de paix.

### LEVER I — Données live > fixtures (latence, 2e source)  ▶ P1 (frein réel)
- Sources : ArbiBot (low-latency WS), ChainInsighter (session/latence).
- Cible : `realtime_monitor/ws_supervisor.py`, `realtime/latency_report.py`.
- Action : prouver la latence ~1-2 s en run Windows, resserrer la fenêtre fraîche ; sinon état vide honnête.
- Mécanisme : la latence mange l'edge des entrées fraîches — c'est LE frein PnL live.

## Séquence recommandée (chaque étape = code + test + backtest A/B)
1. **H** — fiabiliser l'experiment_runner (juge de paix) — sinon on avance à l'aveugle.
2. **A** — approfondir exit_quality + trailing discipliné ; A/B backtest.
3. **C** — consolider entry_quality_gate (verdict unique tracé).
4. **F** — promotion par calibration (ne trader que le calibré).
5. **D** — sizing edge/confiance + halts.
6. **E** — slippage depth-aware + pénalité latence.
7. **I** — latence live (run Windows).
8. **G** — funding/arb quand 2e source live.

## Honnêteté finale
Aucun de ces leviers ne « garantit » un PnL positif. Le chemin réaliste : exits propres (A) + entrées fraîches à edge net réel (B/C) + filtre calibration (F), le tout mesuré en backtest (H). Les gains les plus probables sont A et H ; le frein le plus dur est I (latence live).

---

# BACKLOG COMPLET PnL — toutes les idées intelligentes (githubs + trading)

_2026-07-02. Chaque étape = 1 idée concrète → module cible `src/hl_observer` → source → statut. Aucune ne bypasse RiskEngine/ledger/no-real-trade. Validation backtest avant activation. Statuts : DONE / WIRE (à câbler) / DEEPEN (à approfondir) / TODO / LIVE (attend données live) / DEFER._

## Bloc 1 — Mesure & validation (prérequis : sans juge, pas de vérité)
1. Juge backtest profit factor/drawdown/expectancy — `backtest/experiment_runner` — freqtrade/evan-kolberg — **DONE**
2. Câbler le juge sur logs réels + rapport A/B auto par changement — `backtest/experiment_runner`+CLI — TODO
3. Garde no-lookahead + recursive-bias sur tout backtest — `backtest/no_lookahead_guard` — freqtrade — WIRE(vérifier autoritaire)
4. Walk-forward / out-of-sample split — `backtest/walk_forward` — freqtrade hyperopt — DEEPEN
5. Monte-Carlo sur l'ordre des trades (robustesse drawdown) — `backtest/monte_carlo` — pratique quant — DEEPEN

## Bloc 2 — Qualité d'entrée (moins de trades, plus propres)
6. Gate d'entrée unifié tracé (freshness×edge_net×liquidité×calibration) — `signals/entry_quality_gate` — synthèse — DEEPEN
7. Fraîcheur stricte + decay half-life réglé — `freshness/signal_decay` — Harrier — WIRE(tune)
8. Order Book Imbalance comme confirmation — `features/orderbook_imbalance` — Harrier/mlmodel — WIRE
9. CVD / RVOL / anchored-VWAP / impulse — `features/microstructure` — mlmodelpoly — DEEPEN
10. Scoring smart-money v2 + copyability + tier + decay — `scoring/wallet_score_v2` — Rezzecup — WIRE
11. Consensus multi-wallet + conflict resolver → NO_TRADE si conflit — `copying/*`,`consensus/` — terauss — WIRE
12. Fill confirmé > openOrder (jamais entrer sur openOrder) — `normalization/*` — spec HL — WIRE
13. Filtre liquidité/depth + spread anormal + manipulation flags — `signals/depth_guard`,`entry_quality_gate` — tony — DEEPEN

## Bloc 3 — Exits (LEVIER PnL n°1)
14. Trailing-stop discipliné long/short + score qualité d'exit — `edge/exit_quality` — freqtrade/tony — **DONE**
15. Câbler trailing dans le moteur d'exits (flag env, défaut off) + A/B — `paper_trading/sltp_runtime` — freqtrade — WIRE
16. SL/TP dynamiques basés ATR (volatilité) — `paper_trading/sltp_runtime` — tony/passivbot — TODO
17. Time-stop / max-hold + protection position bloquée — `paper_trading/*`,`risk/loss_halts` — gajesh/passivbot — WIRE
18. Take-profit par paliers (scale-out partiel) — `paper_trading/*` — pratique — TODO
19. Break-even move (SL au prix d'entrée après X bps de profit) — `paper_trading/sltp_runtime` — pratique — TODO

## Bloc 4 — Coûts & réalisme d'exécution
20. Slippage dérivé de la profondeur réelle du carnet L2 — `features/basis`,`backtest/cost_model` — rustjesty — TODO
21. Pénalité latence sur l'edge (edge décroît avec l'âge) — `edge/*` — ArbiBot — WIRE
22. Coût round-trip complet (fees×2+spread+slippage+funding+copy) — `edge/edge_net_v12` — rustjesty — DONE(garder)
23. Partial-fill / missed-fill → risk event (pas de position parfaite) — `paper_trading/fill_*` — rustjesty — DEEPEN

## Bloc 5 — Sizing & risque (protéger l'equity = PnL régulier)
24. Sizing adaptatif ∝ edge net × confiance calibrée — `risk/adaptive_sizing` — MrFadiAi — WIRE
25. Cap d'exposition corrélée (pas 10 positions corrélées) — `risk/correlated_exposure` — passivbot — WIRE
26. Halts perte jour/mois + drawdown kill switch — `risk/loss_halts`,`risk/portfolio_drawdown_kill_switch` — gajesh/MrFadiAi — WIRE
27. Budget VaR/CVaR par position et portefeuille — `risk/var_cvar` — CloddsBot — WIRE
28. Loss-streak halt (pause après N pertes) — `risk/loss_halts` — pratique — WIRE

## Bloc 6 — Sélection & calibration (ne trader que le fiable)
29. Promotion par buckets de confiance calibrés (Brier bas) — `calibration/confidence_buckets`,`calibration/brier` — CloddsBot/evan-kolberg — WIRE
30. Shadow-promotion (tester une stratégie en fantôme avant réel paper) — `strategies/*` — CloddsBot — DEEPEN
31. Quarantaine de stratégie sous-performante — `decision/strategy_quarantine` — pratique — WIRE
32. Régime de marché (trend/chop) → activer/couper stratégies — `market_regime`,`market_signals` — synthèse — DEEPEN

## Bloc 7 — Edge décorrélé (diversifier les sources de PnL) — LIVE requis
33. Funding edge : scanner + spike 2σ + max-hold + drift exit — `funding/*`,`features/funding` — gajesh — LIVE
34. Delta-neutral hedge paper (2 jambes, partial-fill guard) — `paper_trading/delta_neutral*` — rustjesty — LIVE
35. Arbitrage cross-exchange net-of-cost (2e source obligatoire) — `arbitrage/*` — jackhuang/pydevtop — LIVE
36. Arbitrage triangulaire (cycle brut+ mais net− = rejet) — `arbitrage/*`,`strategies/library` — Drakkar — DEFER

## Bloc 8 — Données live & ops (frein n°1 du PnL réel)
37. Latence live ~1-2 s prouvée + fenêtre fraîche resserrée — `realtime_monitor/ws_supervisor`,`realtime/latency_report` — ChainInsighter/ArbiBot — LIVE(Windows)
38. Live > fixtures : vraie donnée HL read-only ou état vide honnête — `collection/*`,`hyperliquid/*` — spec — LIVE
39. Reconnect/backoff/dedupe/gap-recovery WS prouvés — `realtime_monitor/*` — ArbiBot — WIRE
40. Mini-run convergence ledger = audit = dashboard = exports — transverse — spec — TODO

## Ordre d'attaque conseillé (rendement/risque)
Bloc 1 (#2) → Bloc 3 (#15,17,19) → Bloc 2 (#6,8,10) → Bloc 6 (#29,31) → Bloc 5 (#24,25,26) → Bloc 4 (#20,21) → Bloc 8 (#37,38) → Bloc 7 (live).

## Rappel honnête
Aucune étape ne garantit le profit. Ensemble, bien mesurées (Bloc 1), elles maximisent la probabilité d'un PnL paper positif réaliste. On juge au **profit factor**, jamais au winrate brut, et on n'active un levier que s'il améliore l'A/B backtest.

---

# AVANCEMENT 2026-07-02 (R1→R13 bâtis + testés)

Modules créés/étendus dans `src/hl_observer` (purs, testés, additifs, aucun doublon — réutilisent les primitives existantes) :
- **R1** `backtest/ab_report.py` — comparaison A/B au profit factor + verdict KEEP_VARIANT/BASELINE.
- **R1(H)** `backtest/experiment_runner.py` — `summarize_pnl` / `summarize_decisions` (profit factor, drawdown, expectancy).
- **R2/R3/R4** `exits/exit_policy.py` — décision d'exit composée (STOP_LOSS→BREAKEVEN→TP→TRAILING→TIME_STOP) + `atr_sl_tp_bps` (manque ATR comblé). Réutilise `exits/trailing_stop`, `exits/time_stop`, `risk/scale_out`.
- **A** `edge/exit_quality.py` — trailing discipliné + MFE/MAE + score de qualité d'exit.
- **R5/R6/R7/R8** `signals/entry_gate_v2.py` — gate d'entrée unifié tracé (freshness×edge×liquidité×calibration + OBI + fill-confirmé>openOrder + consensus/conflit→NO_TRADE).
- **R9** `calibration/promotion.py` — PROMOTE/SHADOW/QUARANTINE selon calibration.
- **R10** `risk/sizing_v2.py` — taille ∝ edge×confiance + cap corrélé.
- **R11** `risk/risk_gate.py` — halts jour/mois + drawdown kill + loss-streak + VaR unifiés.
- **R12** `backtest/cost_model.py` — `slippage_from_depth_bps` (marche le carnet L2) + `latency_penalty_bps`.
- **R13** `signals/regime_router.py` — trend/chop/extreme → active/coupe les stratégies.

Tests ajoutés : `test_pnl_judge_and_exit_quality.py` (7), `test_exit_policy_and_ab.py` (12), `test_pnl_composition_layers.py` (12). Non-régression : 245 passed sur le périmètre exits/backtest/risk/calibration.

## PARTIAL_NOT_WIRED (honnêteté DoD)
Ces couches sont **codées + testées** mais **pas encore appelées par le runtime live** (`sltp_runtime`, `live_observer`, `ui/routes` = gros fichiers tronqués par le mount, à éditer côté Windows). Plan de câblage : brancher `evaluate_entry_gate` avant PaperIntent, `evaluate_exit` dans la boucle d'exits (flag env, défaut off), `risk_gate`/`sizing_v2` dans le RiskEngine, puis **A/B backtest (R1)** pour n'activer que ce qui monte le profit factor.

## R14 — BLOCKED en sandbox
Latence live ~1-2 s, fixtures→données HL réelles, 2e source arbitrage/funding : nécessitent un **run Windows réel** (le sandbox n'a ni la latence réseau live ni les gros fichiers complets). À exécuter par toi : `LANCER_HYPERSMART.cmd` 15-20 min, puis mesurer.

---

# R1 CÂBLÉ SUR LOGS RÉELS + BASELINE MESURÉE (2026-07-02)

Nouveau : `backtest/pnl_from_logs.py` lit le ledger réel `simulation_decisions_append_only.jsonl` (robuste aux lignes tronquées par le mount), extrait le PnL net par trade clos, et rend profit factor / drawdown / A/B. Runnable : `python -m hl_observer.backtest.pnl_from_logs <log.jsonl> [<variant.jsonl>]`.

**Baseline honnête mesurée sur le log réel actuel (75 trades clos)** :
- winrate 25,3 % · gross_profit 0,00044 · gross_loss 0,1256 · **profit factor 0,0035** · **PnL −0,1252 USDC** · max_drawdown 0,125.
- Lecture : les gains réalisés sont minuscules, les pertes dominent → confirme le diagnostic (exits/gate d'entrée à améliorer, pas la comptabilité). C'est exactement ce que le juge doit révéler, chiffres réels non maquillés.

Exit policy activable par le runtime : `exits/exit_policy.exit_policy_config_from_env()` (deny-by-default, flag `HYPERSMART_EXIT_POLICY_ENABLED`). Prochaine action mesurable : rejouer les logs avec la politique d'exit composée et comparer le profit factor via `ab_logs` (A/B), n'activer que si ça monte.

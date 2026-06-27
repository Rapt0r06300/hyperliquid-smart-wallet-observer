# HYPERSMART OBSERVER — FEUILLE DE ROUTE FUSIONNÉE V9 (Hyperliquid)
## "Toutes les idées des 14 GitHub, fusionnées — rien écarté — pour un bot de copy-trade-wallet parfait"

> **Venue : Hyperliquid uniquement.** Simulation **paper locale branchée sur le vrai marché Hyperliquid** (`/info` REST + WebSocket public, read-only). dYdX abandonné comme cible (le module `dydx_v4/` éventuel reste dormant/isolé, hors scope).
> **Successeur de** `docs/HYPERSMART_FUSION_ROADMAP_V8.md`. **Sources** : `docs/research/fusion/01..14_*.md` (1 fiche/repo). *Le cadrage "dYdX/BAN" de certaines fiches est superseded par ce document.*
> **Compatible agents : Claude *et* Codex.** Chaque slice est autonome, additive, testée.

---

## 0. PRINCIPE DIRECTEUR — on ne jette aucune idée

**Tout est capturé.** Chaque idée des 14 dépôts est intégrée comme **capacité du simulateur**. Rien n'est "interdit" : ce qui touche à l'exécution (construction d'ordre, signature, fills, file d'attente, levier, market-making, arbitrage, MEV…) est **reproduit en simulation**, pas écarté.

**Le simulateur reproduit TOUT sur données réelles :**
signal → décision → **construction d'ordre** → **signature simulée (dry-run)** → **fill simulé au prix réel** → frais/rebates → file d'attente/queue → latence → **PnL marqué au marché réel**, exactement comme si on s'était placé en réel.

**Propriété (pas une restriction) :** une simulation n'a **pas besoin** d'argent réel ni de clé réelle pour refléter fidèlement le marché — elle calcule le « et si on avait placé ça ? » à partir des vrais prix Hyperliquid. C'est *le but* du projet (vérifier si le logiciel produit un PnL paper positif réaliste), pas une limite imposée.

**Honnêteté des données (seule règle dure, voulue par toi) :** **aucune donnée fabriquée / aucune démo.** Données réelles Hyperliquid ou état vide honnête. Donnée incertaine/trop vieille/incomplète → **NO_TRADE** (on préfère ne rien faire que faire un faux trade).

**But quant :** moins de trades, beaucoup plus propres. Filtrer les mauvais signaux ; ne garder que les signaux **frais, cohérents, liquides, à edge net positif** après frais + spread + slippage + latence + dégradation de copie. Jamais de promesse de PnL ; jamais de chiffres maquillés ; on optimise pour maximiser la **probabilité d'un PnL paper positif réaliste**.

**Scraping & collecte :** la collecte publique large (leaderboards, positions, fills, carnets, on-chain) est **encouragée** — c'est le carburant du bot. **Scraping et proxy/rotation sont des outils autorisés et de première classe** — plan complet en §8. (Plus aucune catégorie « interdit » : tout ce que font les dépôts est repris.)

---

## 1. ANCRAGE DANS LE CODE EXISTANT (Hyperliquid)

| Couche | Module existant (à étendre, additif) | Source de données réelle |
|---|---|---|
| Scan / backfill | `hyper_smart_observer/` scanners + `src/hl_observer/` collectors | `/info` REST Hyperliquid |
| Temps réel | `realtime_monitor/ws_supervisor.py` (backoff/dedupe/heartbeat/cap-10/fallback) | WebSocket public HL |
| Stockage | SQLite session (contexts LIVE / BACKTEST / REPLAY / TEST_FIXTURE séparés) | — |
| Normalisation | wallets / positions / orders / fills / coins | `/info` |
| Décision | scoring → shortlist → signaux → no-trade → **edge net** | features marché réelles |
| Exécution **simulée** | `paper_trading/` (PaperEngine, exit_engine, exec model) | mark-to-market prix réels |
| Lifecycle | `position_lifecycle/` (OPEN/ADD/REDUCE/CLOSE) | fills/positions réels |
| Preuve | `DecisionLedger` (+ evidence hash) | — |
| Vue | `src/hl_observer/ui/` dashboard read-only + `/api/simulation/status` | état paper réel |
| Backtest | `backtesting/event_replay.py` + parité | snapshots réels |

**Règle anti-troncature (apprise) :** ne jamais éditer `cli.py` (~2934 l.) / `routes.py` (~3659 l.) via Edit/Write/bash. Ajouter via **nouveaux petits modules** importés.

---

## 2. CATALOGUE UNIFIÉ DES IDÉES (les 14 repos, rien écarté)

Verdicts : **KEEP** (adopter), **ADAPT** (porter sur Hyperliquid/perp), **SIM** (reproduire en simulation paper — y compris ce qui touche l'exécution réelle). *Aucune idée n'est rejetée.*

### 2.1 — Signaux primaires & microstructure
| Idée | Source | Verdict | Module HL cible |
|---|---|---|---|
| **Signal whale on-chain : décoder les entrées des leaders depuis blocs/calldata, 3–30 s d'avance sur l'API publique** | Harrier A1 | **KEEP (signal primaire)** | `signals/whale_fill_signal.py` |
| **Order Book Imbalance (OBI) comme signal autonome, refresh ~500 ms** ("le signal EST le carnet") | Harrier A2, mlmodel A1 | **KEEP** | `features/orderbook_imbalance.py` |
| **CVD** (cumulative volume delta), **RVOL**, **anchored-VWAP**, **impulse**, **liquidations**, **basis** | mlmodelpoly A1 | ADAPT | `features/microstructure.py` |
| **Direction multi-TF (5 m / 15 m) avec TP/SL auto** + **Spread/microstructure** | Harrier | ADAPT | `features/direction.py` |
| **scan_features ultra-riche 70+ colonnes** : lags, ATR multi-période, trade-flow, **âge depuis dernier fill** (ex-`seconds_till_end`) | polyrec A1 | ADAPT | `features/scan_features.py` |
| **Décroissance/âge du signal** (perd sa valeur avec le temps) | Harrier | KEEP | `freshness/signal_decay.py` |

### 2.2 — Probabilité, fair value, edge, calibration
| Idée | Source | Verdict | Module |
|---|---|---|---|
| **Fair-Value model + edge en bps + spike/dip detection** (modes fast/smooth) | mlmodelpoly A2 | ADAPT | `edge/fair_value.py` |
| **Edge NET = brut − frais − spread − slippage − latence − dégradation de copie** | transversal | **KEEP (cœur)** | `edge/edge_calculator.py` |
| **Probabilité calibrée + "model−market difference" + distribution par buckets** | PolyWeather A3 | KEEP | `calibration/model_market.py` |
| **Calibration de confiance par bucket** (win-rate réel par tranche de confiance) | CloddsBot A1 | **KEEP** | `calibration/confidence_buckets.py` |
| **Score de Brier + "cumulative brier advantage"** | pm-backtest A4, PolyWeather | **KEEP** | `calibration/brier.py` |
| **Calibration shadow→primary** : nouveau modèle entraîné hors-ligne, promu si `ready_for_promotion` | PolyWeather A4 | **KEEP** | `calibration/shadow_promote.py` |
| **Biais directionnel multi-TF** 1m/5m/15m/1h (bootstrap HTF klines) | mlmodelpoly A3 | ADAPT | `edge/bias_model.py` |
| **Volatilité fast/slow/blend sigma** (pas qu'un range) | mlmodelpoly A4 | ADAPT | `features/volatility.py` |

### 2.3 — Scoring wallet, smart-money, fidélité de copie
| Idée | Source | Verdict | Module |
|---|---|---|---|
| **Filtre smart-money — seuils exacts** : win-rate ≥ 60 %, PnL ≥ $500, profit-factor ≥ 1.5, consistency ≥ 70 %, one-big-win ≤ 30 % | MrFadiAi A2 | **KEEP** | `scoring/smart_money_filter.py` |
| **Étiquettes de wallet fondées sur preuves** (label exige `evidence_count`) ; smart/whale/suspicious/fresh | awesome-pm A07 | KEEP | `scoring/wallet_labels.py` |
| **Replication / similarity scoring** : écart entre nos paper-trades et les trades réels du leader (tracking error de copie) | polybot, pm-backtest A1 | **KEEP** | `copy_fidelity/` |
| **Execution-quality analysis** : slippage réalisé vs attendu, fill ratio, queue estimée | polybot, pm-backtest A2 | KEEP | `copy_fidelity/exec_quality.py` |
| **Ranking/priorisation de la shortlist** | polyrec | KEEP | `scoring/shortlist_rank.py` |
| **Découverte triée par volume/liquidité** + watchlists avec validation d'adresse | agents, awesome-pm | KEEP | `discovery/` |
| **"Why exact reproduction fails" + external source check** (comprendre pourquoi la copie dévie) | pm-backtest A1 | KEEP | `copy_fidelity/repro_gap.md` |

### 2.4 — Risque, sizing, circuit breakers (paper)
| Idée | Source | Verdict | Module |
|---|---|---|---|
| **Halts de perte multi-couches** : daily 5 % (pause 60 min), monthly 15 % (pause 30 j), drawdown 25 % depuis pic (pause 7 j), **trailing** | MrFadiAi A1 | **KEEP** | `risk/loss_halts.py` |
| **Sizing dynamique par série** : base 2 %, −20 %/perte consécutive, +10 %/gain consécutif (cap 5 %) | MrFadiAi A3 | KEEP | `risk/adaptive_sizing.py` |
| **VaR / CVaR + détection de régime de volatilité (LOW/NORMAL/HIGH/EXTREME) + stress testing + Kelly + daily loss limits** | CloddsBot A2 | **KEEP** | `risk/var_cvar.py` |
| **Circuit Breaker** (halt après N gros trades dans une fenêtre) + **Depth Guard** (valider liquidité du carnet avant chaque décision) | Harrier A4 | **KEEP** | `risk/circuit_breaker.py` |
| **Trade floor / min trade ($1.50)** + **comptabilité frais/gas** (seuil de profit relevé pour couvrir les coûts) | MrFadiAi A4 | KEEP | `risk/trade_floor.py` |
| **Sizing pondéré par la confiance** (couplé Brier) | CloddsBot | KEEP | `risk/adaptive_sizing.py` |

### 2.5 — Données : collecte, normalisation, fraîcheur, robustesse
| Idée | Source | Verdict | Module |
|---|---|---|---|
| **Reconnect / gap-recovery / pagination / déduplication / heartbeat / cap-10 streams user / fallback REST** | transversal + existant | **KEEP** | `realtime_monitor/ws_supervisor.py` |
| **Semaphore rate limiting (25 req/10 s) + budget perf (<1 ms/event, ~200 ms/wallet)** | Harrier A5 | KEEP | `collection/rate_limiter.py` |
| **Connecteurs standardisés (1 client/source → normalise) + modèles Pydantic anti-corruption** ; refus deltas UNKNOWN / closes orphelins / marchés mal mappés | agents, transversal | **KEEP** | `models/` + `connectors/` |
| **Inférence de fills depuis le polling** (FillNotificationTracker) | LP-tool A2 | ADAPT | `normalization/fill_inference.py` |
| **Politique de fraîcheur pilotée par l'observation** (anti-jump : les patches fusionnent, refus signal trop vieux) | PolyWeather A2 | **KEEP** | `freshness/freshness_policy.py` |
| **Quality Mode 3 niveaux OK / DEGRADED / BAD** par flux | mlmodelpoly A5 | **KEEP** | `features/quality_mode.py` |
| **Lazy-load / dégradation gracieuse** : une dépendance optionnelle manquante ne crashe jamais le moteur | CloddsBot A3 | KEEP | `storage/lazy_load.py` |
| **Réconciliation multi-source** (REST vs WS / divergence > seuil → NO_TRADE) | Composio | KEEP | `normalization/reconcile.py` |
| **Whitelist/shortlist rafraîchie périodiquement (120 s) + skip si déjà en position** (cooldown anti-doublon) | LP-tool A3/A4 | KEEP | `discovery/refresh.py` |
| **Config `from_env()` + retries bornés / max_api_errors → halt collecte** | LP-tool A6 | KEEP | `config/defaults.py` |
| **SQLite runtime primaire + runtime data hors git + exports JSON/CSV + historical replay** | PolyWeather A7, PolyTerm A5 | KEEP | `storage/` |
| **Multi-cache "snappy"** : memory + localStorage + backend short-TTL + SSE replay + foreground refresh | PolyWeather A8 | ADAPT | dashboard front |

### 2.6 — Exécution SIMULÉE profonde (tout reproduit, rien envoyé en réel)
| Idée | Source | Verdict | Module |
|---|---|---|---|
| **Common Execution & Data Layer** : Order Builder / Balance Checker / Slippage estimator | CloddsBot | **SIM** | `paper_trading/exec_layer.py` |
| **Modélisation d'exécution profonde** : frais + **maker rebates**, slippage, **passive orders & position de file (queue)**, latence, limites, **comportement L2 vendeur** | pm-backtest A2 | **SIM** | `paper_trading/exec_model.py` |
| **PaperEngine mark-to-market sur prix réels** (equity = capital + realized + unrealized) | existant + projet | **KEEP** | `paper_trading/paper_engine.py` |
| **Lifecycle OPEN / ADD / REDUCE / CLOSE** par wallet/coin/side ; refuse close orphelin | existant + projet | **KEEP** | `position_lifecycle/lifecycle.py` |
| **Construction & signature d'ordre en dry-run** (on bâtit/"signe" pour mesurer, on n'envoie jamais à un endpoint argent-réel) | agents, CloddsBot | **SIM** | `paper_trading/dry_run_order.py` |
| **Stratégies avancées en simulation** : market-making, levier, arbitrage (référence multi-source), MEV, resolution-timing | CloddsBot, Harrier, LP-tool, Composio | **SIM** | `strategies/` (paper) |
| **Validation SL/TP en backtest** + sortie garantie au trade floor | CloddsBot, MrFadiAi | KEEP | `paper_trading/sl_tp.py` |
| **Gate temporel d'éligibilité** ("après N min", cooldown entre entrées) + **forme de signal explicite** (`action`, `edge`, `spread`, statut) | Composio A2/A3 | KEEP | `signals/eligibility.py` |
| **Gates d'exécution** : `STALE_THRESHOLD_SEC=5`, `MIN_DEPTH=200` (veto liquidité), `MAX_SPREAD_BPS=500` (veto), `COOLDOWN_SEC` | mlmodelpoly A7 | **KEEP** | `risk/exec_gates.py` |
| **Inférence côté fill/cancel + reason codes lisibles** | LP-tool A2/A5 | KEEP | `paper_trading/` (NoTradeReason) |

> Le seul fait qui ne change pas : ces composants tournent **en simulation** (pas de connexion argent-réel). C'est *ta* simulation — elle reproduit tout pour mesurer le PnL réaliste.

### 2.7 — Backtest / replay / optimisation
| Idée | Source | Verdict | Module |
|---|---|---|---|
| **Account-ledger replay → interprétation copy-trading** | pm-backtest A1, polyrec A3 | **KEEP** | `backtesting/ledger_replay.py` |
| **Book replay** (orderbook deltas + trades) + **data loading étagé + caches matérialisés + bus unifié + failure semantics** | pm-backtest A5 | ADAPT | `backtesting/book_replay.py` |
| **Backtests dédiés** : `replicate_balance` (réplication de balance d'un wallet), `fade_impulse`, visualisations | polyrec A3 | ADAPT | `backtesting/strategies/` |
| **EXPERIMENT objects / runner contract + parité runtime↔backtest** | pm-backtest A6 | **KEEP** | `backtesting/experiment.py` |
| **Séparation stricte LIVE / BACKTEST / REPLAY / TEST_FIXTURE** (jamais mélanger les PnL) | projet, pm-backtest | **KEEP** | `storage/run_context.py` |
| **Optimisation d'hyper-paramètres** : random-grid + **TPE (Optuna)**, joint multi-replay, avec caveats anti-surajustement | pm-backtest A7 | ADAPT | `backtesting/optimize.py` |
| **Validation walk-forward / out-of-sample** | pm-backtest | KEEP | `backtesting/walk_forward.py` |

### 2.8 — Dashboard, observabilité, preuve, agent-safe
| Idée | Source | Verdict | Module |
|---|---|---|---|
| **Charts canvas (lightweight-charts)** : equity, drawdown, candlesticks **réels** + **markers OPEN/ADD/REDUCE/CLOSE** + price-lines entry/avg/liq | lightweight-charts | **KEEP** | dashboard front |
| **Update incrémental `series.update()`** (anti-jank, pas de re-render complet) | lightweight-charts | KEEP | dashboard front |
| **SSE + révisions + replay de gaps** (`?since_revision=`, patches versionnés) ; stale bloqué pendant refresh | PolyWeather A1 | KEEP | `ui/sse.py` |
| **Suite de charts perf** : equity total + par marché, P&L ticks, P&L periodic bars, market allocation, prix avec fills buy/sell, drawdown, Brier | pm-backtest A3 | KEEP | `ui/perf_charts.py` |
| **Observabilité légère** : `/healthz`, `/api/system/status`, `/metrics` ; **health par sous-système** (REST/WS/SQLite) | PolyWeather A6, polybot, mlmodel | **KEEP** | `ui/health.py` |
| **REST read-only `/latest/features`, `/latest/bars`, `/latest/edge`, `/state`, `/health`** | mlmodelpoly A6 | ADAPT | `ui/latest_routes.py` |
| **Explication de décision = evidence chain + invalidation rules + confirmation rules** ; audit trail + **hash SHA-256** + **block-reasons stats** | PolyWeather A5, CloddsBot A1/A6 | **KEEP** | `evidence/decision_ledger.py` |
| **Journal append-only (1 ligne/décision) + context compacting** (résumés des décisions anciennes) | CloddsBot A5 | KEEP | `evidence/journal.py` |
| **Manifest d'outils agent-safe read-only + JSON Schemas + `llms.txt`** (déjà fait) + **serveur MCP read-only** (FastMCP) | PolyTerm A1/A2/A3/A7 | KEEP / DEFER | `agent_tools/` |
| **Risk panel dashboard** : indicateur LIVE/DRY-RUN, daily/monthly/drawdown/streak (BREACHED/OK), toggles stratégie | MrFadiAi A5 | KEEP | `ui/risk_panel.py` |
| **`secure` report + REPL read-only + doctor** (permissions, secrets, garde-fous, requêtes locales) | CloddsBot A4, PolyTerm A4 | KEEP | `cli` (doctor/secure) |
| **decision_logger structuré + event recording (replay) + Prometheus + JSON logging** | mlmodelpoly A8 | KEEP | `evidence/` |
| **RAG d'evidence offline** : attacher contexte (news/why) à une décision a posteriori (hors hot path) | agents | DEFER (recherche) | `research/rag_evidence/` |

### 2.9 — Architecture & process
| Idée | Source | Verdict | Module |
|---|---|---|---|
| **Architecture propre par étages** : pipeline / features / bars / edge_engine / fair_model / bias_model / volatility / accumulate_engine / decision_logger | mlmodelpoly A9 | KEEP | structure `hyper_smart_observer/` |
| **Séparation modulaire** : MainLoop / PricePolicy / OrderBookFetcher / RewardMonitor / RiskManager / FillNotificationTracker / Config | LP-tool A1 | KEEP | idem |
| **Séparation ingestion / strategy / analytics / exécution(paper) / orchestration** + **orchestrator relançable** (gap-recovery au redémarrage) | polybot | KEEP | `orchestrator.py` |
| **Mode runtime nommé `PAPER`** (explicite ; LIVE = simulation, jamais argent réel) | polybot | KEEP | `runtime_mode.py` |
| **CLI par commande** (`scan`, `backtest`, `replay`, `dashboard`, `doctor`, `safety-audit`) | agents, existant | KEEP | `cli.py` (via petits modules) |
| **Patron de spec de stratégie** (1 MD : hypothèse, signal, filtres, edge attendu, invalidations) | polybot | KEEP | `docs/strategies/` |
| **Catalogue de sources de données** pour la recherche | awesome-pm | KEEP | `docs/research/DATA_SOURCES.md` |
| **Sanitation des entrées agent + échec gracieux + zéro custody** | PolyTerm A6 | KEEP | `agent_tools/` |
| **Gates de test : repo gate standard + smoke checks + docs validation** | pm-backtest A8 | KEEP | `tests/` |

---

## 3. SLICES EXÉCUTABLES (Hyperliquid — pour Claude **et** Codex)

**Protocole par slice :** 1) `git status` + lire l'existant ; 2) **petits modules neufs** (jamais éditer `cli.py`/`routes.py`) ; 3) code + tests ; 4) run tests + `safety-audit` ; 5) vérifier données réelles only + NO_TRADE par défaut ; 6) rapport FR ; 7) ne pas committer/pusher depuis le sandbox. Chaque slice est **additive** et **indépendamment livrable**. **DoD** = Definition of Done.

### S0 — Fondations & contexte de run
- **Créer :** `runtime_mode.py` (mode `PAPER` nommé), `storage/run_context.py` (`RunContext{LIVE,BACKTEST,REPLAY,TEST_FIXTURE}` → PnL jamais mélangés), `config/defaults.py` (config `from_env()`, deny-by-default, retries bornés / `max_api_errors`).
- **Tests :** `test_safety_no_real_order`, `test_config_safe_defaults`, `test_run_context_isolation`.
- **DoD :** moteur démarre ; PnL paper isolé par contexte. *(polybot, LP-tool A6, pm-backtest)*

### S1 — Modèles & normalisation (frontière anti-corruption)
- **Créer :** `models/` (Pydantic : `Wallet`, `Position`, `Order`, `Fill`, `Coin`, `Candle`, `BookLevel`), `normalization/normalize.py` (refus UNKNOWN/orphelin/mal-mappé), `normalization/reconcile.py` (REST vs WS → NO_TRADE si divergence), `normalization/fill_inference.py`.
- **Tests :** `test_reject_unknown_delta`, `test_reject_orphan_close`, `test_reconcile_divergence_no_trade`, `test_fill_inference`.
- **DoD :** toute donnée entrante validée ou rejetée proprement. *(agents, LP-tool A2, Composio)*

### S2 — Collecte REST `/info` (snapshots/backfill)
- **Créer :** `collection/rest_client.py` (read-only, pagination, retry/backoff), `collection/rate_limiter.py` (sémaphore 25 req/10 s + budget perf), `storage/sqlite_store.py` (upsert idempotent → dédup), `discovery/refresh.py` (shortlist triée volume, refresh 120 s, skip si déjà en position).
- **Tests :** `test_rest_mocked`, `test_pagination`, `test_dedupe`, `test_backfill_idempotent`, `test_rate_limiter`.
- **DoD :** backfill rejoué 2× → 0 doublon. *(Harrier A5, agents, LP-tool A3/A4)*

### S3 — Temps réel WebSocket
- **Étendre :** `realtime_monitor/ws_supervisor.py` (reconnect backoff, **gap-recovery via REST**, heartbeat, dedupe, fallback, **cap 10 streams user**).
- **Tests :** `test_ws_mocked`, `test_reconnect`, `test_gap_recovery`, `test_ws_cap_10_user_streams`, `test_heartbeat_timeout_fallback`.
- **DoD :** coupure simulée → reconnect + comble le gap sans doublon. *(transversal + existant)*

### S4 — Features marché (réelles, jamais fabriquées)
- **Créer :** `features/orderbook_imbalance.py` (OBI), `features/microstructure.py` (CVD/RVOL/anchored-VWAP/impulse/liquidations/basis), `features/direction.py` (5 m/15 m), `features/scan_features.py` (70+ cols), `features/volatility.py` (fast/slow/blend), `features/quality_mode.py` (OK/DEGRADED/BAD), `freshness/signal_decay.py`.
- **Tests :** `test_features_deterministic`, `test_quality_mode_levels`, `test_features_empty_data_no_fabrication`.
- **DoD :** données absentes → feature `None`/quality basse, **jamais** inventée. *(mlmodelpoly A1/A3/A4/A5, Harrier A2, polyrec A1)*

### S5 — Scoring wallet, smart-money, fidélité de copie
- **Créer :** `scoring/smart_money_filter.py` (seuils 60 %/$500/1.5/70 %/30 %), `scoring/wallet_labels.py` (label = evidence_count), `scoring/shortlist_rank.py`, `copy_fidelity/` (tracking error), `copy_fidelity/exec_quality.py`.
- **Tests :** `test_smart_money_thresholds`, `test_wallet_label_requires_evidence`, `test_copy_fidelity_tracking_error`.
- **DoD :** wallet sous seuil exclu ; shortlist non plafonnée par artefact de process. *(MrFadiAi A2, awesome-pm, polybot, pm-backtest A1)*

### S6 — Signaux, fraîcheur, edge net, no-trade
- **Créer :** `signals/whale_fill_signal.py` (primaire, 3–30 s d'avance), `signals/eligibility.py` (gate temporel + forme explicite), `freshness/freshness_policy.py` (anti-jump, refus trop vieux), `edge/fair_value.py`, `edge/edge_calculator.py` (edge **net**), `edge/bias_model.py`, `risk/exec_gates.py` (STALE=5 s, MIN_DEPTH=200, MAX_SPREAD_BPS=500, COOLDOWN), `risk/risk_engine.py` (deny-by-default).
- **Tests :** `test_stale_signal_refused`, `test_low_edge_refused`, `test_low_liquidity_refused`, `test_wide_spread_refused`, `test_signal_is_not_order`, `test_deny_by_default`.
- **DoD :** majorité des signaux → NO_TRADE avec raison tracée. *(Harrier A1, PolyWeather A2/A3, mlmodelpoly A2/A7, Composio A2)*

### S7 — Risque, sizing, circuit breakers, calibration
- **Créer :** `risk/var_cvar.py` (VaR/CVaR + régime vol + stress + Kelly), `risk/loss_halts.py` (daily 5 / monthly 15 / drawdown 25 / trailing), `risk/adaptive_sizing.py` (streak + confiance), `risk/circuit_breaker.py` (+ depth guard), `risk/trade_floor.py` (+ frais/gas), `calibration/confidence_buckets.py`, `calibration/brier.py`, `calibration/model_market.py`, `calibration/shadow_promote.py`.
- **Tests :** `test_loss_halts_levels`, `test_adaptive_sizing_streak`, `test_circuit_breaker`, `test_depth_guard`, `test_brier_score`, `test_shadow_not_acting`.
- **DoD :** au-delà d'un palier de perte paper, sizing réduit puis halt ; Brier calculé. *(CloddsBot A1/A2, MrFadiAi A1/A3/A4, Harrier A4, PolyWeather A4)*

### S8 — Exécution SIMULÉE profonde (PaperEngine)
- **Créer :** `paper_trading/paper_engine.py` (mark-to-market prix réels), `paper_trading/exec_model.py` (frais + maker rebates, slippage, queue, latence, L2), `paper_trading/exec_layer.py` (Order Builder / Balance Checker / Slippage), `paper_trading/dry_run_order.py` (build+sign **simulés**, jamais envoyés réel), `paper_trading/sl_tp.py`, `position_lifecycle/lifecycle.py`, `strategies/` (market-making/levier/arb **paper**).
- **Tests :** `test_pnl_long_correct`, `test_pnl_short_correct`, `test_fees_not_double_counted`, `test_lifecycle_open_add_reduce_close`, `test_no_orphan_close`, `test_mark_to_market_real_price_only`, `test_dry_run_never_sends`.
- **DoD :** PnL long & short justes ; frais comptés une fois ; tout simulé, rien envoyé réel. *(pm-backtest A2, CloddsBot, MrFadiAi A4, existant)*

### S9 — Backtest / Replay / optimisation
- **Créer :** `backtesting/ledger_replay.py` (→ interprétation copy-trading), `backtesting/book_replay.py` (deltas + trades), `backtesting/experiment.py` (parité runtime↔backtest), `backtesting/walk_forward.py`, `backtesting/optimize.py` (random-grid + TPE/Optuna), `backtesting/strategies/` (replicate_balance, fade_impulse).
- **Tests :** `test_replay_deterministic`, `test_backtest_live_parity`, `test_context_isolation`, `test_replay_pnl_not_in_live`.
- **DoD :** replay = mêmes décisions que live sur mêmes données ; PnL replay séparé. *(pm-backtest A1/A5/A6/A7, polyrec A3)*

### S10 — Dashboard read-only, evidence, observabilité
- **Créer :** `ui/health.py` (`/healthz`+`/metrics`+health par sous-système), `ui/sse.py` (patch+revision+gap-replay), `ui/latest_routes.py` (`/latest/*`), `ui/perf_charts.py`, `ui/risk_panel.py` (LIVE/DRY-RUN + streaks), `evidence/decision_ledger.py` (evidence chain + invalidation/confirmation + hash + block-reason stats), `evidence/journal.py` (append-only + compacting) ; front **lightweight-charts** (candles réelles + markers lifecycle + `series.update`).
- **Tests :** `test_dashboard_read_only`, `test_dashboard_empty_state_no_fake`, `test_decision_ledger_evidence`, `test_health_per_subsystem`.
- **DoD :** état vide honnête sans données ; aucune route n'agit en réel. *(PolyWeather A1/A5/A6, lightweight-charts, mlmodelpoly A6/A8, MrFadiAi A5)*

### S11 — CLI, docs, audit, MCP read-only
- **Créer/MAJ :** commandes CLI (via petits modules) `scan`/`backtest`/`replay`/`dashboard`/`doctor`/`secure`/`safety-audit` ; `docs/strategies/` (1 MD/stratégie) ; `docs/research/DATA_SOURCES.md` ; option serveur **MCP read-only** (FastMCP) exposant le manifest agent-safe.
- **Tests :** `test_audit_safety` (0 ordre réel multi-dossier), `test_agent_tools_read_only`.
- **DoD :** `safety-audit` → preuve 0 ordre réel ; manifest agent-safe exposable. *(PolyTerm A1/A4/A7, CloddsBot A4, agents)*

---

## 4. MAPPING vers les TESTS obligatoires
| Test | Slice |
|---|---|
| Sécurité : aucun ordre réel possible | S0, S8, S11 |
| Config safe par défaut | S0 |
| REST mocké | S2 |
| WebSocket mocké | S3 |
| Reconnect | S3 |
| Gap recovery | S3 |
| Dedupe | S2 |
| Pagination | S2 |
| Lifecycle OPEN/ADD/REDUCE/CLOSE | S8 |
| Stale signal refusé | S6 |
| Edge trop faible refusé | S6 |
| Liquidité trop faible refusée | S6 |
| PnL long/short correct | S8 |
| Fees non doublés | S8 |
| Séparation LIVE/BACKTEST/REPLAY/TEST_FIXTURE | S0, S9 |
| Dashboard read-only | S10 |

---

## 5. PREUVE DE COUVERTURE — les 14 repos, rien oublié

| # | Repo | Fiche | Idées intégrées (exhaustif) | Slices |
|---|---|---|---|---|
| 01 | CloddsBot | `01_CLODDSBOT_DEEP.md` | Calibration confiance par bucket (A1) ; VaR/CVaR+régime vol+stress+Kelly+daily-loss (A2) ; lazy-load gracieux (A3) ; `secure`+REPL+doctor (A4) ; journal append-only+compacting (A5) ; block-reason stats (A6) ; Common Exec & Data Layer ; SL/TP backtest ; MCP read-only | S7, S8, S10, S11, S2 |
| 02 | Harrier | `02_HARRIER.md` | **Whale on-chain 3–30 s (A1)** ; OBI autonome 500 ms (A2) ; venue adapter (A3, n/a HL-only) ; circuit breaker+depth guard (A4) ; semaphore 25 req/10 s+budget perf (A5) ; Direction 5/15 m+TP/SL ; Spread | S6, S4, S7, S2 |
| 03 | MrFadiAi | `03_MRFADIAI.md` | Loss-halts daily5/monthly15/dd25/trailing (A1) ; smart-money seuils 60/$500/1.5/70/30 (A2) ; sizing streak −20/+10 cap5 (A3) ; trade floor+gas (A4) ; risk panel LIVE/DRY-RUN (A5) | S7, S5, S10 |
| 04 | Polymarket-LP-tool | `04_POLYMARKET_LP_TOOL.md` | Séparation modulaire+FillNotificationTracker (A1) ; fill inference polling (A2) ; whitelist refresh 120 s (A3) ; skip si en position (A4) ; reason codes (A5) ; from_env+retries bornés (A6) ; market-making **simulé** | S2.9-arch, S1, S2, S8 |
| 05 | PolyWeather | `05_POLYWEATHER.md` | SSE+revisions+gap-replay (A1) ; **freshness anti-jump (A2)** ; proba calibrée+model−market+buckets (A3) ; shadow→primary (A4) ; evidence chain+invalidation+confirmation (A5) ; /healthz//metrics//status (A6) ; SQLite primaire hors-git (A7) ; multi-cache (A8) | S10, S6, S7 |
| 06 | Composio-arb | `06_COMPOSIO_ARB.md` | Status endpoints read-only (A1) ; gate temporel "after N min" (A2) ; forme de signal explicite (A3) ; poll interval+cooldown (A4) ; réconciliation multi-source ; arb **simulé** | S6, S1, S8 |
| 07 | awesome-pm-tools | `07_AWESOME_PM_TOOLS.md` | Analytics dashboard, API feeds, copy-trading cœur, wallet analytics/leaderboards, alertes off-par-défaut, snapshots, odds/spread/liquidity/depth, watchlists validées, labels fondés-preuves, portfolio paper | S10, S5, S4 |
| 08 | PolyTerm | `08_POLYTERM.md` | Manifest agent-safe (A1) ; JSON schemas (A2) ; llms.txt (A3) ; doctor (A4) ; SQLite+exports+replay (A5) ; sanitation+graceful+zero-custody (A6) ; serveur MCP read-only (A7) | S11, S2 |
| 09 | mlmodelpoly | `09_MLMODELPOLY.md` | Microstructure CVD/RVOL/VWAP/impulse/liquidations/basis (A1) ; fair-value+edge bps+spike/dip (A2) ; bias multi-TF (A3) ; vol fast/slow/blend (A4) ; **quality mode 3 niveaux (A5)** ; `/latest/*` (A6) ; gates STALE5/DEPTH200/SPREAD500/cooldown (A7) ; decision_logger+replay+metrics (A8) ; archi par étages (A9) | S4, S6, S10 |
| 10 | polyrec | `10_POLYREC.md` | **scan_features 70+ cols (A1)** ; logging CSV par marché (A2) ; backtests replicate_balance+fade_impulse+viz (A3) | S4, S9 |
| 11 | prediction-market-backtesting | `11_PM_BACKTESTING.md` | **Ledger replay→copy-interpretation+why-fails+external-check (A1)** ; **exec modeling profond maker/queue/L2/latence (A2)** ; suite charts perf (A3) ; **Brier (A4)** ; book replay+caches+failure-semantics (A5) ; EXPERIMENT+parité (A6) ; TPE/Optuna+multi-replay (A7) ; gates de test (A8) | S9, S8, S10, S7 |
| 12 | polybot | `12_POLYBOT.md` | Séparation services+orchestrator relançable ; mode PAPER nommé ; health par sous-système ; **replication & similarity scoring** ; execution-quality analysis | S0, S3, S5, S10 |
| 13 | Polymarket/agents | `13_POLYMARKET_AGENTS.md` | **Connecteurs standardisés+Pydantic anti-corruption** ; RAG offline evidence ; CLI par commande ; tri par volume | S1, S2, S11 |
| 14 | tradingview/lightweight-charts | `14_LIGHTWEIGHT_CHARTS.md` | Charts canvas equity/drawdown/candles + **markers prix-réel × évènements-paper** ; `series.update` anti-jank ; price-lines | S10 |

**Vérification :** 14/14 repos ; toutes les sous-idées A1–A9 tracées ; **aucune idée écartée** (l'exécution est *simulée*, pas interdite) ; seule règle dure = données réelles only, pas de fabrication.

---

## 6. ORDRE D'EXÉCUTION POUR AGENTS

```
S0 ─► S1 ─► S2 ─► S3 ─┐
            │         ├─► S4 ─► S5 ─► S6 ─► S7
            │                          │
            └──────────────────────────┼─► S8 ─► S9 ─► S10 ─► S11
```
Chaque slice : modules neufs + tests + `safety-audit`. Indépendamment livrable. Ne pas committer/pusher depuis le sandbox.

---

## 7. CLÔTURE

Cette feuille de route **capture toutes les idées des 14 dépôts**, sans rien écarter : ce qui touche à l'exécution est **reproduit en simulation paper** sur les vraies données Hyperliquid (mark-to-market prix réels). C'est **ta** simulation : elle mesure « et si on s'était placé en réel ? » sans avoir besoin d'argent ni de clé.

**Seule règle dure (la tienne) :** données réelles uniquement, **aucune démo / aucune fabrication** ; donnée douteuse → **NO_TRADE**. Jamais de promesse de PnL.

*Venue : Hyperliquid uniquement. Sources détaillées : `docs/research/fusion/01..14_*.md`.*
---

## 8. COLLECTE À GRANDE ÉCHELLE — SCRAPING + PROXY (outils autorisés)

> **Tout est autorisé ici, comme dans les dépôts analysés.** Scraping de données publiques + **pool de proxies avec rotation** sont des outils de collecte de **première classe**. Objectif : maximiser le volume et la continuité de la donnée publique Hyperliquid qui alimente la simulation. On combine rotation **et** backoff/politesse non par prudence morale mais parce que c'est ce qui **maximise le taux de succès et la qualité des données** (un proxy cramé ne sert plus).

### 8.1 — Limites officielles Hyperliquid (vérifiées juin 2026, utiles pour calibrer)
**Par IP :** budget REST **1200 de poids/minute**. Poids `info` : **2** (`l2Book, allMids, clearinghouseState, orderStatus, spotClearinghouseState, exchangeStatus`), **60** (`userRole`), **20** (autres) ; poids additionnel /20 items (`recentTrades, userFills…`) ou /60 items (`candleSnapshot`) ; `explorer`=**40**.
**WebSocket :** 10 connexions, 30 nouvelles conn/min, 1000 souscriptions, **10 users uniques** (= notre cap-10), 2000 msg/min, 100 posts in-flight.
**Adresse :** la limite « 1 req/1 USDC tradé » **ne vise que les *actions* (trading)**, **pas `info`** → en lecture seule, **seul le poids/IP nous concerne**. C'est pourquoi **multiplier les IP via proxies décuple directement le débit de collecte**.
**Bulk :** bucket **S3** officiel pour l'historique massif.

### 8.2 — Pool de proxies intelligent (le plan, cohérent & méthodique)
**`collection/proxy_pool.py`** — un pool d'IP de sortie (datacenter et/ou résidentiel, selon ce que tu fournis) avec, pour chaque proxy : budget de poids propre (1200/min), score de santé, compteurs (succès, 429/403, latence), état (ACTIF / COOLDOWN / RETIRÉ).

**Stratégies de rotation (configurables) :**
1. **Sticky-by-shard (par défaut, recommandé)** : on partitionne le travail par clé (coin, ou tranche de wallets) et on **épingle chaque shard à un proxy**. Données stables, dédup trivial, ordre préservé, chaque IP reste sous sa limite → débit = N × budget.
2. **Round-robin / par-requête** : rotation à chaque requête pour les scans larges sans état.
3. **Par-session** : un proxy gardé le temps d'une session (cookies/headers cohérents) pour le scraping HTML.

**Rotation automatique sur signal d'effort** : sur `429`/`403`/timeout/challenge → le proxy passe en **COOLDOWN exponentiel**, son shard **bascule** sur un proxy ACTIF, puis revient quand il est sain. Détection de ban (statut/again challenge) → **retrait + remplacement** transparents.

**Gestion d'identité par proxy** : **User-Agent et en-têtes rotatifs** cohérents par session, jitter temporel, concurrence bornée par proxy (sémaphore ~25 req/10 s). Sessions/cookies isolées par proxy pour le scraping de pages.

**Fournisseurs** : compatible proxies datacenter, résidentiels et mobiles (HTTP/HTTPS/SOCKS5) via config `proxy_pool = [...]` ; clés/identifiants proxy en variables d'environnement.

### 8.3 — Budgeteur de poids agrégé
**`collection/weight_budgeter.py`** — token-bucket **par proxy** calibré à 1200 wt/min (cible 70–90 % selon ton appétit). Débit global = somme des buckets. Débite le poids exact (table 8.1). Deux budgets séparés (Data/Trading) ; Trading=0 en paper → tout le budget sert la donnée.

### 8.4 — Sources de collecte
- **WebSocket d'abord** (trades, `l2Book`, `allMids`, events user) → pression REST quasi nulle, latence minimale.
- **REST `/info`** pour snapshots/backfills (paginé, dédupliqué).
- **Scraping HTML** (`collection/html_scraper.py`) pour tout ce qui n'est pas dans l'API documentée (ex. pages leaderboard/UI publiques) : parsing robuste, via le pool de proxies, sessions gérées.
- **Bulk S3** pour l'historique profond ; **node Hyperliquid propre** et **fournisseurs data** (Chainstack, HyperPC, Dwellir) pour le très gros volume.

### 8.5 — Résilience requête
Backoff exponentiel + jitter ; respect de `Retry-After` ; **circuit breaker par proxy** ; retries bornés (`max_api_errors`) ; coalescing + cache TTL court ; dédup SQLite ; backfill lourd hors-pointe. Dégradation gracieuse → quality mode `DEGRADED/BAD` (jamais de donnée fabriquée).

### 8.6 — Monitoring & pilotage
Tableau interne : taux de succès / 429 / latence **par proxy**, poids consommé/min, msgs WS/min, souscriptions, users uniques (≤10). Auto-rotation des proxies faibles, auto-throttle global à l'approche des budgets, retrait/réintégration automatiques. Alertes off par défaut (read-only).

### 8.7 — Slices & tests (extension S2/S3)
**S2bis — Pool & budget :** `collection/proxy_pool.py`, `collection/weight_budgeter.py`, `collection/rate_limiter.py`, `collection/backoff.py`, `collection/circuit_breaker.py`, `collection/html_scraper.py`.
**Tests :** `test_proxy_rotation_on_429`, `test_sticky_sharding_no_overlap`, `test_failover_then_recover`, `test_weight_never_exceeds_budget_per_proxy`, `test_aggregate_throughput_scales_with_pool`, `test_backoff_retry_after`, `test_circuit_breaker_per_proxy`, `test_header_ua_rotation`, `test_html_scraper_parses_real_fixture`, `test_ws_caps` (10/1000/10/2000), `test_degrade_when_budget_low_no_fabrication`.

**Sources :** [Hyperliquid — Rate limits and user limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) · [WS subscription limits & best practices (nktkas/DeepWiki)](https://deepwiki.com/nktkas/hyperliquid/6.4-subscription-limits-and-best-practices) · [Hyperliquid rate limits & best practices (OneKey)](https://onekey.so/blog/ecosystem/hyperliquid-rate-limits-best-practices/) · [WebSocket subscription limits (Dwellir)](https://www.dwellir.com/blog/hyperliquid-websocket-subscription-limits) · [Hyperliquid infrastructure & RPC nodes (Chainstack)](https://docs.chainstack.com/docs/hyperliquid-infrastructure-faq)

---

*Venue : Hyperliquid uniquement. Aucune catégorie « interdit » : toutes les techniques des 14 dépôts (scraping, proxy/rotation, features, signaux, exécution simulée) sont reprises. Seule constante : données réelles, aucune fabrication ; donnée douteuse → NO_TRADE.*


---

# HYPERSMART OBSERVER — FEUILLE DE ROUTE FUSIONNÉE V10
## Addendum "Audit profond des 14 GitHub + logique complète scan/décision/simulation"

> **Cette V10 ne supprime rien de la V9.**  
> Elle ajoute une couche plus opérationnelle pour qu’un agent Claude/Codex sache quoi coder, dans quel ordre, comment scanner, comment décider, comment simuler, comment backtester et comment prouver qu’on a vraiment récupéré le meilleur des 14 GitHub.
>
> Règle centrale inchangée : **Hyperliquid par défaut, simulation paper locale, données réelles uniquement, aucune exécution argent-réel.**
>
> Ne pas bloquer sur les mots `scraping`, `proxy`, `trade`, `buy`, `sell`, `copy`, `order`, `CLOB`, `Polymarket`, `Kalshi`, `execution`, `signature`, `wallet`. Ces mots sont autorisés dans recherche, parsing public, simulation, tests, backtest, dashboard, PaperEngine et docs. Ils deviennent dangereux uniquement s’ils déclenchent une action argent-réel externe.

---

## V10.0 — Ce que V10 ajoute à V9

La V9 capturait déjà les idées principales. La V10 ajoute ce qui manquait encore pour une feuille de route d’agent de codage autonome :

1. grille d’adaptation plus claire pour les 14 GitHub ;
2. compléments repo par repo ;
3. architecture cible plus complète ;
4. logique de scan complète ;
5. logique de décision complète ;
6. taxonomie `NO_TRADE` complète ;
7. catalogue de stratégies simulées ;
8. exécution simulée profonde ;
9. dashboard final attendu ;
10. matrice de couverture V10 ;
11. ordre de livraison par gros blocs.

---

## V10.1 — Nouvelle grille pour récupérer 100 % des idées

Chaque idée trouvée dans un GitHub doit recevoir une destination :

```text
RESEARCH_SOURCE      = source à lire/analyser
HYPERLIQUID_ADAPT    = à porter sur Hyperliquid read-only
PAPER_SIM            = à reproduire en simulation locale
DASHBOARD            = à rendre visible
BACKTEST             = à rejouer/tester
EVIDENCE             = à tracer dans ledger/hash/source refs
DEFER_SCALE          = architecture lourde à garder pour plus tard
REAL_ACTION_BLOCKED  = seulement si action argent-réel externe
```

Aucune idée ne doit être jetée parce qu’elle vient de Polymarket/Kalshi/CLOB. La transformation obligatoire est : **tout devient Hyperliquid + simulation locale**.

---

## V10.2 — Compléments par GitHub à ne pas oublier

### 01 — CloddsBot

À ajouter/renforcer :

- WebChat local avec sidebar `Chats / Projects / Artifacts / Code`.
- Artifacts auto-extraits : rapports, snippets, décisions, backtests.
- Historique SQLite paginé, search, context compacting.
- CLI `doctor`, `secure`, `repl`, `mcp`.
- 118+ stratégies comme catalogue d’idées.
- unified strategy & risk layer.
- VaR/CVaR, volatility regime, stress testing, Kelly sizing, daily loss limits, kill switch paper.
- Skills lazy-loaded : dépendances optionnelles qui ne crashent pas.
- MCP server comme modèle agent-safe.
- Decision audit trail + confidence calibration + SHA-256.
- Whale/copy tracking sur plusieurs sources.
- Security shield à transformer en audit local.

Modules :
`ui/webchat_like_dashboard/`, `artifacts/`, `diagnostics/doctor.py`, `diagnostics/secure.py`, `evidence/decision_ledger.py`, `evidence/context_compaction.py`, `risk/var_cvar.py`, `risk/kill_switch_paper.py`, `skills/optional_registry.py`, `agent_tools/mcp_readonly.py`.

Tests :
`test_artifacts_created_after_scan`, `test_context_compaction_preserves_decision_summary`, `test_doctor_reports_source_health_and_runtime_paths`, `test_secure_reports_no_real_action`, `test_optional_skill_missing_dependency_does_not_crash`, `test_decision_ledger_sha256_stable`.

### 02 — Harrier

À ajouter/renforcer :

- "One observation core. One paper execution core. One risk layer. Every data source."
- Les 10 stratégies deviennent des stratégies paper.
- Full dry-run support devient simulation verrouillée.
- Circuit breaker, depth guard, cooldown, min trade floor.
- Adapter stack devient `ReadOnlySourceAdapter`.

Stratégies à simuler :
copy trading, BTC 5m/15m/1h arbitrage, cross-market arbitrage, direction hunting, market making, spread farming, whale alerts, orderbook imbalance, fast timing, venue/source adapters.

Modules :
`core/observation_core.py`, `core/paper_execution_core.py`, `sources/base_adapter.py`, `sources/hyperliquid_adapter.py`, `sources/public_web_adapter.py`, `strategies/paper_registry.py`, `strategies/copy_follow.py`, `strategies/orderbook_imbalance.py`, `strategies/arbitrage_sim.py`, `strategies/market_making_sim.py`, `risk/depth_guard.py`, `risk/circuit_breaker.py`.

Tests :
`test_every_strategy_goes_through_risk_engine`, `test_strategy_registry_has_no_external_action`, `test_copy_strategy_builds_paper_intent_only`, `test_market_making_strategy_simulates_only`.

### 03 — MrFadiAi Polymarket-bot

À ajouter/renforcer :

- 4-layer risk protection : daily 5 %, monthly 15 %, drawdown 25 %, total halt 40 %.
- Smart-money thresholds : winrate ≥ 60 %, PnL ≥ 500 $, profit factor ≥ 1.5, consistency ≥ 70 %, one-big-win ≤ 30 %.
- Dynamic sizing : reduce during losses, increase cautiously during wins, caps.
- Risk breach alerts.
- Fee/spread/slippage/funding accounting.

Modules :
`scoring/smart_money_filter.py`, `scoring/wallet_score_v2.py`, `scoring/copyability_score.py`, `risk/loss_halts.py`, `risk/adaptive_sizing.py`, `risk/breach_alerts.py`, `paper_trading/cost_accounting.py`, `ui/risk_panel.py`.

Tests :
`test_smart_money_threshold_exact_values`, `test_one_big_win_reduces_copyability`, `test_daily_loss_5_percent_halts_paper`, `test_monthly_loss_15_percent_halts_paper`, `test_drawdown_25_percent_halts_paper`, `test_total_loss_40_percent_freezes_paper`, `test_dynamic_sizing_loss_streak`.

### 04 — Polymarket LP Tool

À ajouter/renforcer :

- WebSocket-first + REST reconciliation.
- Deterministic simple rules.
- midpoint jump filter.
- stable confirmation.
- EMA/median smoothing.
- fill cooldown.
- max chase.
- JSON rule store.
- local command/status model inspiré `/status`, `/orders`, `/pnl`, `/set_rule`.

Modules :
`realtime/ws_first_runtime.py`, `realtime/rest_reconciler.py`, `features/midpoint_jump_filter.py`, `features/mid_stability.py`, `features/ema_median_smoother.py`, `copy_mode/cooldown.py`, `paper_trading/max_chase_guard.py`, `config/local_rule_store.py`, `ui/local_commands.py`.

Tests :
`test_ws_first_then_rest_reconcile`, `test_midpoint_jump_filter_blocks_signal`, `test_stable_confirmation_requires_multiple_ticks`, `test_ema_median_smoothing_does_not_create_fake_price`, `test_fill_cooldown_blocks_duplicate`, `test_max_chase_blocks_degraded_copy`.

### 05 — PolyWeather

À ajouter/renforcer :

- SSE `/api/events`.
- Redis Stream ou SQLite Event Log.
- SQLite runtime state.
- healthz/system/status/metrics.
- chart patches.
- replay missed events.
- no-patch fallback refresh.
- foreground catch-up refresh.
- full HTTP authoritative snapshot.
- stale data blocked during refresh.
- CSS tokens/responsive/accessibility.

Modules :
`ui/sse_events.py`, `ui/dashboard_events.py`, `ui/authoritative_snapshot.py`, `ui/stale_policy.py`, `ui/full_refresh_fallback.py`, `ui/frontend_tokens.css`, `storage/runtime_state.py`, `storage/event_log.py`.

Tests :
`test_sse_event_revision_increments`, `test_dashboard_replay_missed_events`, `test_stale_refresh_blocks_paper_ready_signal`, `test_full_snapshot_authoritative`, `test_no_patch_fallback_refresh`.

### 06 — Composio polymarket-kalshi-arbitrage-bot

À ajouter/renforcer :

- `/health`, `/status`, `/poll/start`, `/poll/stop`.
- scanner_running, last prices, current signal, start window.
- timing gate.
- spread/edge comparator.
- arbitrage simulation only.

Modules :
`api/health.py`, `api/status.py`, `scanner/control.py`, `scanner/timing_gate.py`, `signals/current_signal.py`, `strategies/arbitrage_sim.py`.

Tests :
`test_health_endpoint_readonly`, `test_status_contains_scanner_state_and_current_signal`, `test_poll_start_stop_local_only`, `test_timing_gate_blocks_too_early_signal`, `test_arbitrage_signal_becomes_paper_strategy`.

### 07 — Awesome Prediction Market Tools

À ajouter/renforcer :

- Benchmark produit type Bloomberg : live odds, spreads, liquidity, orderbook depth, arbitrage opportunities, historical data.
- Copy score 1-10.
- PnL analysis, Sharpe, max drawdown, red flags, category breakdown.
- AI Agents, APIs, aggregators, alerts, analytics, dashboards, data, portfolio tracking, trading bots.

Modules :
`product_benchmark/feature_matrix.py`, `ui/bloomberg_like_market_panel.py`, `ui/wallet_analytics_panel.py`, `ui/copyability_score_panel.py`, `ui/red_flags_panel.py`, `ui/market_depth_panel.py`, `watchlists/`, `alerts/local_alerts_off_by_default.py`.

Tests :
`test_benchmark_matrix_has_all_product_categories`, `test_copyability_score_panel_uses_evidence`, `test_red_flags_panel_requires_data`, `test_alerts_disabled_by_default`, `test_watchlist_import_export_validates_wallets`.

### 08 — PolyTerm

À ajouter/renforcer :

- 20+ analytics.
- 73+ TUI screens.
- Agent manifest.
- JSON schemas.
- FastMCP stdio server.
- legacy JSON-lines adapter.
- doctor diagnostics.
- `llms.txt`, `llms-full.txt`.
- SQLite DB.
- bookmarks, alerts, paper trade journal, paper position tracking, screener presets.
- zero custody.
- terminal-native charts.

Modules :
`agent_tools/manifest.py`, `agent_tools/schemas/`, `agent_tools/mcp_server_readonly.py`, `agent_tools/jsonl_adapter.py`, `docs/llms.txt`, `docs/llms-full.txt`, `cli/doctor.py`, `cli/tui_status.py`, `storage/bookmarks.py`, `storage/local_alerts.py`, `paper_trading/journal.py`, `paper_trading/position_tracking.py`, `screeners/presets.py`.

Tests :
`test_agent_manifest_contains_only_safe_tools`, `test_json_schemas_validate_outputs`, `test_mcp_server_exposes_readonly_and_local_simulation_tools`, `test_doctor_checks_sqlite_and_hyperliquid_sources`, `test_zero_custody_no_private_key_fields`.

### 09 — mlmodelpoly

À ajouter/renforcer :

- WS streams.
- OHLCV bars.
- CVD, VWAP, RVOL, impulse, microprice, basis, anchored VWAP, liquidation tracking.
- volatility, fair value model, edge calculation.
- TUI dashboard.
- REST `/health`, `/state`, `/latest/features`, `/latest/bars`, `/latest/edge`.
- warmup behavior.
- configurable depth/TOPN.

Modules :
`features/bars.py`, `features/trade_flow.py`, `features/cvd.py`, `features/vwap.py`, `features/rvol.py`, `features/impulse.py`, `features/microprice.py`, `features/basis.py`, `features/liquidation_tracker.py`, `edge/fair_value_model.py`, `api/latest_features.py`, `api/latest_bars.py`, `api/latest_edge.py`.

Tests :
`test_bars_ohlcv_from_candles_or_trades`, `test_cvd_from_trade_flow`, `test_vwap_from_real_trades_only`, `test_rvol_requires_volume_window`, `test_microprice_from_l2`, `test_fair_value_edge_bps`, `test_latest_routes_no_fake_values`.

### 10 — polyrec

À ajouter/renforcer :

- 70+ CSV columns.
- Terminal dashboard.
- multi-source reconciliation.
- orderbook 5 levels.
- spread, imbalance, microprice, slope, eat-flow.
- returns, volume, volatility, ATR/RVOL.
- automatic CSV logging.
- backtesting scripts.

Modules :
`features/scan_features_schema.py`, `features/depth_slope.py`, `features/eat_flow.py`, `features/returns.py`, `features/atr.py`, `features/rvol.py`, `exports/scan_features_csv.py`, `exports/scan_features_json.py`, `cli/terminal_dashboard.py`, `backtesting/visual_reports.py`.

Tests :
`test_scan_features_has_minimum_70_columns`, `test_csv_json_export_parity`, `test_orderbook_5_levels_extracted`, `test_depth_slope_calculated`, `test_eat_flow_from_trade_stream`, `test_no_fake_csv_rows`.

### 11 — prediction-market-backtesting

À ajouter/renforcer :

- Nautilus-inspired architecture.
- Custom adapters.
- staged data loading.
- materialized caches.
- unified cache/local/archive/API bus.
- book replay from orderbook deltas + trade ticks.
- EXPERIMENT objects.
- runner contracts.
- joint portfolio multi replay.
- Optuna/TPE.
- equity/PnL ticks/drawdown/Sharpe/monthly returns.
- cumulative Brier advantage.
- local data mirrors.
- execution modeling : fees, maker rebates, slippage, passive order/queue position, latency, L2 behavior.

Modules :
`backtesting/data_bus.py`, `backtesting/materialized_cache.py`, `backtesting/book_replay.py`, `backtesting/trade_tick_replay.py`, `backtesting/experiment.py`, `backtesting/runner_contract.py`, `backtesting/multi_wallet_replay.py`, `backtesting/optimize.py`, `backtesting/walk_forward.py`, `backtesting/report_charts.py`, `paper_trading/queue_model.py`, `paper_trading/maker_rebate_model.py`, `paper_trading/latency_model.py`.

Tests :
`test_backtest_no_lookahead`, `test_book_replay_reconstructs_l2_state`, `test_trade_tick_replay_orders_events`, `test_runner_contract_validates_inputs`, `test_experiment_outputs_report`, `test_queue_model_affects_fill_probability`, `test_maker_rebates_in_cost_model`.

### 12 — polybot

À ajouter/renforcer :

- multi-service architecture as conceptual boundary.
- ingestion, strategy, analytics, monitoring, orchestration.
- ClickHouse/Redpanda/Grafana/Prometheus as DEFER scale.
- paper/live mode separation concept.
- market/user trade ingestion.
- quantitative analysis.
- replication scoring.
- research snapshots.
- execution quality.

Modules :
`architecture/README_SERVICES.md`, `orchestrator/local_orchestrator.py`, `ingestion/`, `analytics/`, `monitoring/metrics.py`, `copy_fidelity/replication_score.py`, `copy_fidelity/execution_quality.py`, `research/snapshots.py`.

Tests :
`test_local_orchestrator_recovers_after_restart`, `test_paper_mode_is_default`, `test_health_per_subsystem`, `test_replication_score_calculated`, `test_execution_quality_report`, `test_no_clickhouse_required_now`.

### 13 — Polymarket/agents

À ajouter/renforcer :

- Pydantic objects.
- connectors.
- RAG/news/evidence.
- CLI commands.
- local data.
- agent decomposition.
- API interaction examples as research/dry-run only.

Modules :
`connectors/base.py`, `connectors/hyperliquid_readonly.py`, `connectors/public_research.py`, `research/rag_evidence/`, `research/decision_explainer.py`, `research/wallet_thesis.py`, `models/pydantic_core.py`, `cli/research_commands.py`.

Tests :
`test_connector_normalizes_to_common_models`, `test_research_rag_does_not_change_decisions_hot_path`, `test_decision_explainer_uses_evidence_refs`, `test_wallet_thesis_has_sources`, `test_no_real_trade_action_in_connectors`.

### 14 — TradingView lightweight-charts

À ajouter/renforcer :

- performant canvas charts.
- candlesticks.
- line/area/histogram.
- markers.
- price lines.
- incremental updates with `series.update`.
- multi-pane charting.
- crosshair.
- responsive UI.

Modules :
`ui/charts/equity_chart.ts`, `ui/charts/drawdown_chart.ts`, `ui/charts/candle_chart.ts`, `ui/charts/position_markers.ts`, `ui/charts/edge_chart.ts`, `ui/charts/liquidity_chart.ts`, `ui/charts/source_latency_chart.ts`, `ui/charts/no_trade_markers.ts`, `ui/charts/incremental_update.ts`.

Tests :
`test_chart_empty_state_has_no_fake_points`, `test_chart_series_comes_from_db_or_export`, `test_position_markers_match_paper_trades`, `test_no_trade_markers_match_ledger`, `test_incremental_update_does_not_rebuild_full_chart`.

---

## V10.3 — Architecture cible finale

```text
PUBLIC SOURCES + HYPERLIQUID READ-ONLY
        |
        v
SourceRegistry + PublicScraper + HyperliquidInfoClient + HyperliquidWSClient
        |
        v
ProxyPool + WeightBudgeter + RateLimiter + Backoff + CircuitBreaker
        |
        v
RawStore + Provenance + SourceHealth + EventLog
        |
        v
Common Pydantic Models + Normalization + Reconciliation + Dedupe
        |
        v
Wallet Discovery + Leaderboard + Watchlists + ShortlistRank
        |
        v
Fills / Positions / OpenOrders / L2Book / Candles / Trades
        |
        v
PositionLifecycle + LeaderDelta + MarketFeatures + Volatility + Microstructure
        |
        v
WalletScore + CopyabilityScore + PatternDetector + ClusterDetector
        |
        v
SignalCandidate + EdgeNet + RiskEngine + NO_TRADE Reasons
        |
        +--> DecisionLedger / EvidenceChain / Journal
        |
        +--> PaperEngine / ExecModel / DryRunOrder / Queue / Fees / Slippage
        |
        v
PaperPortfolio + PnL + Equity + Drawdown + CopyFidelity
        |
        v
Backtest / Replay / WalkForward / Optimization
        |
        v
Dashboard + API Readonly/Local Simulation + Charts + Exports + Agent Tools
```

---

## V10.4 — Logique de scan complète

### Phase A — Source Registry

Créer un registre local des sources :

```text
source_id
source_type: HYPERLIQUID_INFO | HYPERLIQUID_WS | PUBLIC_HTML | PUBLIC_API | GITHUB | USER_FILE | BULK_S3
url_or_endpoint
read_only
requires_secret
requires_login
rate_limit_policy
cache_ttl
last_fetch_ts
last_status
raw_hash
parsed_hash
provenance
```

### Phase B — Discovery wallets

Découvrir les wallets via :

- seed wallets utilisateur ;
- watchlists ;
- leaderboards publics ;
- gros volumes Hyperliquid ;
- fills récents ;
- positions notables ;
- open interest/crowded flows si disponible ;
- pages publiques ;
- datasets historiques ;
- imports CSV/JSON ;
- résultats précédents.

### Phase C — Backfill wallet

Pour chaque wallet :

- `clearinghouseState`;
- `userFillsByTime`;
- `userFills`;
- `openOrders` / `frontendOpenOrders` comme contexte ;
- fees/funding si disponible ;
- positions ;
- recent fills ;
- cursors time-range ;
- dedupe.

### Phase D — Market context

Pour chaque coin actif :

- `allMids`;
- `l2Book`;
- trades WS ;
- candleSnapshot ;
- orderbook depth ;
- liquidity ;
- spread ;
- volatility ;
- microprice ;
- trade flow ;
- source health.

### Phase E — Normalization

- raw hash ;
- Pydantic validation ;
- dedupe ;
- source health ;
- data quality ;
- stale detection ;
- fallback/reconciliation.

### Phase F — Intelligence

- wallet score ;
- copyability ;
- risk flags ;
- patterns ;
- clusters ;
- labels ;
- source confidence.

### Phase G — Runtime

- shortlist max 10 user-specific streams ;
- market streams for active coins ;
- heartbeat ;
- reconnect ;
- snapshots ;
- event persistence ;
- REST reconcile.

---

## V10.5 — Logique de décision complète

Chaque signal doit passer cette matrice :

```text
1. SourceHealth OK?
2. Wallet in shortlist?
3. WalletScore enough?
4. Copyability enough?
5. Lifecycle event understood?
6. Signal fresh?
7. Current market data available?
8. Spread acceptable?
9. Depth/liquidity acceptable?
10. Volatility regime acceptable?
11. Edge net positive after all costs?
12. Copy degradation below max?
13. Portfolio exposure acceptable?
14. Cooldown OK?
15. Loss halts OK?
16. Duplicate guard OK?
17. PaperEngine can model it?
18. EvidenceChain can explain it?
```

Si un point critique manque : `NO_TRADE`.  
Mais un `NO_TRADE` doit toujours être utile : raison claire, preuve, donnée manquante, prochaine action.

---

## V10.6 — Taxonomie `NO_TRADE`

À implémenter ou aligner :

```text
INSUFFICIENT_DATA
SOURCE_STALE
SOURCE_DEGRADED
SOURCE_CONFLICT
RATE_LIMITED
WALLET_NOT_SCORED
WALLET_SCORE_TOO_LOW
COPYABILITY_TOO_LOW
ONE_BIG_WIN_RISK
PNL_CONCENTRATION_RISK
HIGH_DRAWDOWN_RISK
INACTIVE_WALLET
SUSPICIOUS_WALLET
LIFECYCLE_UNKNOWN
ORPHAN_CLOSE
AMBIGUOUS_FLIP
DUPLICATE_SIGNAL
SIGNAL_TOO_OLD
OPEN_ORDERS_CONTEXT_ONLY
MID_MISSING
L2BOOK_MISSING
SPREAD_TOO_WIDE
LIQUIDITY_TOO_LOW
DEPTH_TOO_LOW
VOLATILITY_TOO_HIGH
EDGE_UNMEASURABLE
EDGE_REMAINING_TOO_LOW
COPY_DEGRADATION_TOO_HIGH
COOLDOWN_ACTIVE
PORTFOLIO_EXPOSURE_TOO_HIGH
MAX_OPEN_POSITIONS
BLOCKED_ASSET
LOSS_HALT_ACTIVE
CIRCUIT_BREAKER_ACTIVE
PAPER_ENGINE_CANNOT_MODEL
NO_MATCHING_PAPER_POSITION
BACKTEST_CONTEXT_ONLY
DASHBOARD_EMPTY_STATE
```

---

## V10.7 — Stratégies simulées à prévoir

Chaque stratégie doit être `paper-only` :

1. Copy wallet.
2. Follow open only.
3. Follow open + close.
4. Follow reduce/close only if paper position exists.
5. Fade impulse.
6. Follow impulse.
7. Orderbook imbalance.
8. Whale fill early.
9. Direction multi-TF.
10. Mean reversion.
11. Momentum.
12. Spread/liquidity.
13. Market making simulation.
14. Arbitrage simulation.
15. Cross-source discrepancy.
16. Volatility breakout.
17. Low-vol scalping.
18. DCA simulation.
19. Kelly/confidence sizing.
20. Strategy ensemble.
21. Shadow model.
22. RAG evidence context only.

Chaque stratégie doit définir :

```text
hypothesis
required_data
entry_condition
exit_condition
risk_gates
cost_model
no_trade_conditions
paper_metrics
backtest_metrics
dashboard_view
tests
```

---

## V10.8 — Exécution simulée profonde

Le PaperEngine doit simuler :

- market order ;
- limit order ;
- post-only idea ;
- maker/taker ;
- rebates ;
- queue position ;
- partial fills ;
- missed fills ;
- latency ;
- spread ;
- slippage ;
- L2 depth ;
- max chase ;
- funding ;
- liquidation event ;
- leverage scenario ;
- close/reduce ;
- TP/SL ;
- time stop ;
- trailing stop ;
- MAE/MFE ;
- notional caps ;
- position sizing ;
- portfolio exposure ;
- cash/equity/margin simulation.

Chaque paper action doit avoir :

```text
paper_action_id
not_an_order=true
simulation_only=true
external_action=false
source_signal_id
decision_id
evidence_chain_id
cost_breakdown
fill_model
confidence
```

---

## V10.9 — Dashboard final attendu

Pages/panels :

```text
Overview
Runtime status
Source health
Proxy health
Rate budget
Scanner status
Wallet discovery
Shortlist
Wallet leaderboard
Wallet detail
Wallet labels
Smart-money filters
Pattern detector
Cluster detector
Market features
Orderbook depth
Microstructure
Volatility regime
Signal candidates
NO_TRADE reasons
Decision ledger
Evidence chain
Paper portfolio
Paper positions
Paper trades
Lifecycle events
Copy fidelity
Execution quality
Risk panel
Loss halts
Backtests
Replay runs
Optimization results
Charts
Artifacts
Exports
Doctor
Safety audit
Data sources
```

Aucun écran ne doit afficher de faux trade. Si vide : `No data yet`.

---

## V10.10 — Matrice de couverture V10

Créer :

```text
docs/research/HYPERSMART_V10_COVERAGE_MATRIX.md
```

Colonnes :

```text
Repo
Idea
Source proof
V9 status
V10 added detail
Module target
Test target
Implementation status
```

Tests globaux :

```text
test_v10_every_repo_has_coverage_matrix
test_v10_every_idea_has_module_and_test
test_v10_no_external_real_action
test_v10_simulated_actions_allowed
test_v10_public_scraping_allowed_with_source_registry
test_v10_paper_engine_has_deep_exec_model
test_v10_dashboard_no_fake_data
test_v10_backtest_no_lookahead
test_v10_evidence_chain_complete
```

---

## V10.11 — Ordre de livraison conseillé

### Bloc 1 — Base de scan intelligente
S0 + S1 + S2 + S2bis + SourceRegistry + ProxyPool + WeightBudgeter + Normalization.

### Bloc 2 — Temps réel et features
S3 + S4 + WS supervisor + microstructure + volatility + 70+ scan features.

### Bloc 3 — Intelligence wallet
S5 + WalletScore + Copyability + Labels + PatternDetector + ClusterDetector.

### Bloc 4 — Décision
S6 + EdgeNet + RiskEngine + NO_TRADE taxonomy + EvidenceChain.

### Bloc 5 — Simulation profonde
S8 + PaperEngine + DryRunOrder + ExecModel + Queue + CostModel + Lifecycle + ExitEngine.

### Bloc 6 — Backtest
S9 + LedgerReplay + BookReplay + Experiment + WalkForward + Optimization.

### Bloc 7 — Produit
S10 + Dashboard + Charts + Artifacts + Search + Reports + Agent tools.

### Bloc 8 — QA/Release
S11 + safety audit + clean archive + docs + continuation status.

---

## V10.12 — Objectif Codex recommandé

```text
Lis AGENTS.md puis docs/HYPERSMART_FUSION_ROADMAP_V10.md. Travaille local only dans C:\Users\flo\Desktop\Projet invest. Ne supprime rien. Applique la V10 par gros blocs: scan+collecte, WS+features, wallet intelligence, décision/no_trade, PaperEngine simulation profonde, backtest, dashboard, QA. Tout est autorisé en recherche/read-only/simulation locale/outils locaux; seule limite dure: aucune action argent-réel externe et aucune donnée fabriquée. Code réel, tests, safety-audit, rapport FR, fichier de reprise si tout n'est pas terminé.
```

---

## V10.13 — Phrase finale pour agents

> Fusionner toutes les idées des 14 GitHub dans HyperSmart, en Hyperliquid par défaut, simulation locale paper, données réelles uniquement, aucune action argent-réel, aucune donnée fabriquée, aucun oubli non documenté.


---

# HYPERSMART OBSERVER — FEUILLE DE ROUTE FUSIONNÉE V11
## Roadmap ultra-opérationnelle pour agent IA autonome
### "Structure complète + logique de scan + décision + simulation + tests + dashboard"

> **Cette V11 ne supprime rien de la V9/V10.**  
> Elle ajoute une couche beaucoup plus précise pour guider un agent Claude/Codex : quoi coder, où coder, quels réglages prévoir, quelles tables créer, quelles APIs exposer, quels tests écrire, et comment décider par gros blocs.
>
> Doctrine définitive :
>
> - Runtime par défaut : **Hyperliquid**.
> - Mode : **simulation paper locale**.
> - Données : **vraies données marché / vraies données publiques / vrai état local**, jamais de démo inventée.
> - Tout concept des 14 GitHub est récupérable : scraping, proxy, CLOB, trade, buy, sell, copy, order, execution, market-making, arbitrage, signature, wallet, agents.
> - Ces concepts sont **reproduits en simulation locale**, pas utilisés pour agir sur de l'argent réel.
> - Seules frontières dures :
>   - aucune action argent-réel externe ;
>   - aucune private key / seed / mnemonic réelle pour trader ;
>   - aucune signature envoyée ;
>   - aucun dépôt/retrait/transfert ;
>   - aucune donnée fabriquée pour remplir un écran ;
>   - donnée douteuse, trop vieille ou incomplète → `NO_TRADE`.

---

## V11.0 — Comment un agent doit lire cette roadmap

Un agent de codage ne doit pas lire cette roadmap comme une simple liste d'idées. Il doit la traiter comme un **contrat de construction**.

### Méthode obligatoire

1. Lire `AGENTS.md`.
2. Lire cette roadmap V11.
3. Lire le code existant avant de coder.
4. Ne pas réécrire les gros fichiers sensibles.
5. Créer de petits modules importables.
6. Coder une vertical slice complète.
7. Ajouter tests.
8. Lancer validations.
9. Écrire rapport FR.
10. Mettre à jour le statut d'avancement.

### Fichiers de suivi à créer/maintenir

```text
docs/research/HYPERSMART_V11_CURRENT_STATE.md
docs/research/HYPERSMART_V11_GITHUB_IDEA_COVERAGE.md
docs/research/HYPERSMART_V11_IMPLEMENTATION_STATUS.md
docs/research/HYPERSMART_V11_NEXT_STEPS.md
```

### Statuts autorisés

```text
DONE
PARTIAL
BLOCKED
DEFER_SCALE
NEEDS_TESTS
NEEDS_DASHBOARD
NEEDS_BACKTEST
NEEDS_EVIDENCE
```

---

## V11.1 — Cartographie des capacités finales

HyperSmart doit être découpé en capacités indépendantes mais reliées :

```text
A. Source Registry
B. Collection REST /info
C. Scraping public + proxies + cache
D. WebSocket supervisor
E. RawStore + provenance
F. Normalisation Pydantic
G. Reconciliation + dedupe
H. Wallet discovery
I. Wallet scoring
J. Position lifecycle
K. Market features
L. Edge / fair value / calibration
M. Strategy registry paper-only
N. RiskEngine
O. DecisionLedger / EvidenceChain
P. PaperEngine simulation profonde
Q. ExitEngine
R. Backtest / Replay / Walk-forward / Optimization
S. Dashboard / API / Charts
T. Agent tools / MCP / CLI
U. Safety audit / archive / release
```

Chaque capacité doit avoir :

```text
module
config
input model
output model
DB table
events
tests
dashboard panel
report/export
```

---

## V11.2 — Source Registry et collecte publique

### But

Centraliser toutes les sources de données, y compris Hyperliquid et les sources publiques utilisées pour la recherche.

### Modules à créer ou renforcer

```text
hyper_smart_observer/sources/registry.py
hyper_smart_observer/sources/models.py
hyper_smart_observer/sources/provenance.py
hyper_smart_observer/collection/public_scraper.py
hyper_smart_observer/collection/html_scraper.py
hyper_smart_observer/collection/proxy_pool.py
hyper_smart_observer/collection/weight_budgeter.py
hyper_smart_observer/collection/backoff.py
hyper_smart_observer/collection/circuit_breaker.py
hyper_smart_observer/collection/cache.py
```

### Modèle `SourceDefinition`

```text
source_id
source_name
source_kind: HYPERLIQUID_INFO | HYPERLIQUID_WS | PUBLIC_HTML | PUBLIC_API | GITHUB | USER_FILE | BULK_S3
url_or_endpoint
adapter_name
enabled
read_only
requires_login
requires_secret
allowed_context: LIVE | BACKTEST | RESEARCH | TEST_FIXTURE
rate_limit_policy
proxy_policy
cache_ttl_seconds
robots_policy_note
last_fetch_ts
last_success_ts
last_error
```

### Modèle `FetchProvenance`

```text
fetch_id
source_id
url
method
status_code
fetched_at
latency_ms
proxy_id
cache_hit
raw_hash
parsed_hash
content_type
parser_version
data_quality
```

### Réglages à prévoir

```text
HYPERSMART_PUBLIC_SCRAPER_ENABLED=1
HYPERSMART_PROXY_POOL_ENABLED=0|1
HYPERSMART_PROXY_STICKY_SHARDS=1
HYPERSMART_FETCH_CACHE_TTL_SEC=30
HYPERSMART_MAX_PUBLIC_FETCHES_PER_RUN=...
HYPERSMART_MAX_FETCH_RETRIES=3
HYPERSMART_SCRAPER_RESPECT_RETRY_AFTER=1
```

### Règles

- Scraping public autorisé.
- Pas de contournement login/captcha/paywall.
- Proxies autorisés pour robustesse/continuité, avec budgets par sortie.
- Tout résultat doit avoir provenance + hash.
- Toute source incertaine doit dégrader la qualité, pas fabriquer des données.

### Tests

```text
test_source_registry_validates_public_sources
test_scraper_public_only_no_login_required
test_fetch_provenance_hashes_raw_and_parsed
test_proxy_pool_sticky_shards
test_proxy_rotation_on_429
test_weight_budget_per_proxy
test_cache_prevents_duplicate_fetches
test_bad_source_degrades_quality_no_fake
```

---

## V11.3 — Hyperliquid Read-Only Data Layer

### But

Créer une couche Hyperliquid solide, bornée, traçable et testable.

### Modules

```text
hyper_smart_observer/hyperliquid_client/info_readonly.py
hyper_smart_observer/hyperliquid_client/ws_readonly.py
hyper_smart_observer/hyperliquid_client/pagination.py
hyper_smart_observer/hyperliquid_client/rate_weights.py
hyper_smart_observer/hyperliquid_client/normalizers.py
```

### Endpoints /info à couvrir

```text
allMids
l2Book
candleSnapshot
recentTrades
clearinghouseState
userFills
userFillsByTime
openOrders
frontendOpenOrders
orderStatus
userFees
exchangeStatus
```

### WebSocket channels à couvrir

```text
allMids
l2Book
trades
bbo
candle
userFills
userEvents
openOrders
clearinghouseState
```

### Output standard de chaque appel

```text
request_id
endpoint_or_channel
payload_hash
source_ts
local_received_ts
latency_ms
rate_weight
raw_ref
raw_hash
data_quality
source_health_id
pagination_state
```

### Tests

```text
test_info_client_all_mids_readonly
test_info_client_l2_book_readonly
test_candle_snapshot_normalized
test_user_fills_by_time_paginates_500_blocks
test_rate_weight_matches_endpoint
test_ws_snapshot_then_update_dedupe
test_ws_caps_user_streams_10
test_no_exchange_endpoint_used
```

---

## V11.4 — RawStore, EventLog, SQLite schema

### But

Ne plus perdre de données, pouvoir rejouer, auditer et backtester.

### Tables minimales

```text
source_definitions
fetch_provenance
raw_events
collection_runs
source_health
wallets
wallet_snapshots
fills_raw
fills_normalized
positions_raw
positions_normalized
open_orders_context
market_mids
l2_books
candles
trades
market_features
wallet_scores
copyability_scores
position_lifecycle_events
leader_deltas
signal_candidates
risk_decisions
no_trade_decisions
paper_intents
paper_orders_simulated
paper_fills_simulated
paper_trades
paper_positions
paper_portfolio_snapshots
decision_ledger
evidence_chain
backtest_runs
backtest_events
dashboard_snapshots
proxy_health
artifacts
```

### Règles SQLite

- WAL mode si utile.
- migrations versionnées.
- unique constraints pour idempotence.
- raw JSON conservé avec hash.
- contextes `LIVE`, `BACKTEST`, `REPLAY`, `TEST_FIXTURE`.
- ne jamais mélanger PnL de contextes différents.

### Tests

```text
test_sqlite_migrations_idempotent
test_raw_event_hash_unique
test_contexts_never_mix_pnl
test_replay_can_read_raw_events
test_duplicate_fill_not_inserted_twice
```

---

## V11.5 — Normalisation et anti-corruption

### But

Ne jamais laisser une donnée externe polluer le moteur.

### Modules

```text
hyper_smart_observer/normalization/fills.py
hyper_smart_observer/normalization/positions.py
hyper_smart_observer/normalization/orders_context.py
hyper_smart_observer/normalization/markets.py
hyper_smart_observer/normalization/reconcile.py
hyper_smart_observer/normalization/dedupe.py
```

### Modèle `NormalizedFill`

```text
fill_id
venue
wallet
coin
side
dir
px
sz
time
start_position
closed_pnl
fee
fee_token
builder_fee
hash
oid
tid
crossed
liquidation
raw_ref
raw_hash
source_health_id
```

### Règles

- `openOrders` = contexte, jamais signal seul.
- `orderStatus` = diagnostic, jamais preuve seule.
- fill sans prix/taille/temps -> rejet ou degraded.
- close orphelin -> `ORPHAN_CLOSE`.
- delta inconnu -> `LIFECYCLE_UNKNOWN`.
- conflit REST/WS -> `SOURCE_CONFLICT`.

### Tests

```text
test_normalized_fill_required_fields
test_open_orders_context_only
test_order_status_diagnostic_only
test_orphan_close_no_trade
test_rest_ws_conflict_no_trade
```

---

## V11.6 — Position Lifecycle Engine

### But

Comprendre ce que fait réellement un leader : ouvre, ajoute, réduit, ferme, flip, liquidation.

### Modules

```text
hyper_smart_observer/position_lifecycle/reconstructor.py
hyper_smart_observer/position_lifecycle/episode.py
hyper_smart_observer/position_lifecycle/confidence.py
hyper_smart_observer/position_lifecycle/exports.py
```

### Events

```text
OPEN_LONG
OPEN_SHORT
ADD_LONG
ADD_SHORT
INCREASE_LONG
INCREASE_SHORT
REDUCE_LONG
REDUCE_SHORT
CLOSE_LONG
CLOSE_SHORT
FLIP_LONG_TO_SHORT
FLIP_SHORT_TO_LONG
LIQUIDATION
FEE_ONLY
UNKNOWN
```

### Champs `PositionLifecycleEvent`

```text
event_id
wallet
coin
side_before
side_after
event_type
event_time
source_fill_ids
source_hashes
start_position
end_position_estimate
avg_px
total_sz
closed_pnl
fees
holding_time_ms
confidence
ambiguity_reason
```

### Tests

```text
test_lifecycle_open_long
test_lifecycle_open_short
test_lifecycle_add_long
test_lifecycle_reduce_long
test_lifecycle_close_long
test_lifecycle_flip_long_to_short
test_lifecycle_partial_close
test_lifecycle_liquidation
test_lifecycle_unknown_no_trade
```

---

## V11.7 — LeaderDelta et signalisation

### But

Transformer les événements de leaders en signaux actionnables en simulation.

### Modules

```text
hyper_smart_observer/signals/leader_delta.py
hyper_smart_observer/signals/signal_candidate.py
hyper_smart_observer/signals/eligibility.py
hyper_smart_observer/signals/freshness.py
hyper_smart_observer/signals/decay.py
```

### Delta

```text
delta_id
wallet
coin
action: OPEN | ADD | INCREASE | REDUCE | CLOSE | FLIP | IGNORE
side
size
reference_price
leader_time
observed_time
latency_ms
freshness_score
source_event_id
confidence
```

### Règles

- OPEN/ADD/INCREASE -> potentiel PaperIntent.
- REDUCE/CLOSE/FLIP -> ExitEngine si position paper existe.
- UNKNOWN -> NO_TRADE.
- stale -> NO_TRADE.
- duplicate -> ignore + journaliser.
- openOrders seuls -> `OPEN_ORDERS_CONTEXT_ONLY`.

### Tests

```text
test_open_event_creates_signal_candidate
test_reduce_routes_to_exit_engine
test_close_routes_to_exit_engine
test_unknown_lifecycle_no_trade
test_stale_delta_no_trade
test_duplicate_delta_ignored
```

---

## V11.8 — Market Features, microstructure, volatility

### Modules

```text
features/orderbook_imbalance.py
features/microstructure.py
features/bars.py
features/trade_flow.py
features/cvd.py
features/vwap.py
features/rvol.py
features/impulse.py
features/microprice.py
features/basis.py
features/liquidation_tracker.py
features/volatility.py
features/quality_mode.py
features/scan_features_schema.py
features/depth_slope.py
features/eat_flow.py
features/returns.py
features/atr.py
```

### Champs `MarketFeatureSnapshot`

```text
feature_id
run_id
coin
current_mid
mid_source
best_bid
best_ask
spread_bps
bid_depth_1
ask_depth_1
bid_depth_5
ask_depth_5
bid_depth_10
ask_depth_10
depth_imbalance
microprice
depth_slope
trade_count
trade_flow_delta
cvd
vwap
anchored_vwap
rvol
impulse_score
liquidation_score
basis_bps
candle_return_1m
candle_return_5m
candle_return_15m
realized_vol_bps
vol_fast
vol_slow
vol_blend
atr_bps
quality_mode
source_health_id
feature_hash
```

### Tests

```text
test_market_features_no_fake_when_missing_data
test_orderbook_imbalance_calculation
test_cvd_from_trade_flow
test_vwap_from_real_trades_only
test_microprice_from_l2
test_volatility_fast_slow_blend
test_scan_features_minimum_70_columns
```

---

## V11.9 — Wallet Intelligence

### Modules

```text
scoring/wallet_score_v2.py
scoring/smart_money_filter.py
scoring/copyability_score.py
scoring/wallet_labels.py
scoring/shortlist_rank.py
scoring/red_flags.py
copy_fidelity/replication_score.py
copy_fidelity/execution_quality.py
copy_fidelity/repro_gap.py
patterns/pattern_detector.py
patterns/cluster_detector.py
```

### Scores

```text
winrate
realized_pnl
closed_pnl
profit_factor
consistency_score
one_big_win_ratio
pnl_concentration
max_drawdown
sharpe
sortino
calmar
avg_holding_time
cuts_losses_score
lets_winners_run_score
adds_to_winners_score
averages_down_penalty
overtrading_score
liquidation_count
copy_delay_sensitivity
exit_followability
copyability_score
```

### Tests

```text
test_wallet_score_requires_minimum_evidence
test_smart_money_thresholds
test_copyability_penalizes_fast_unfollowable_wallet
test_one_big_win_penalty
test_pnl_concentration_penalty
test_cluster_detector_finds_grouped_entries
```

---

## V11.10 — EdgeNet, décision, risk

### Modules

```text
edge/fair_value_model.py
edge/edge_calculator.py
edge/bias_model.py
edge/model_market.py
calibration/confidence_buckets.py
calibration/brier.py
calibration/shadow_promote.py
risk/risk_engine.py
risk/exec_gates.py
risk/loss_halts.py
risk/adaptive_sizing.py
risk/var_cvar.py
risk/circuit_breaker.py
risk/depth_guard.py
risk/trade_floor.py
risk/portfolio_exposure.py
```

### Edge net

```text
gross_edge_bps
fees_bps
spread_cost_bps
slippage_bps
latency_penalty_bps
copy_degradation_bps
volatility_penalty_bps
liquidity_penalty_bps
funding_estimate_bps
net_edge_bps
decision_threshold_bps
```

### Décision gates

```text
source_health
wallet_score
copyability
lifecycle_confidence
freshness
spread
depth
liquidity
volatility
edge_net
cooldown
portfolio_exposure
loss_halts
circuit_breaker
paper_engine_modelable
evidence_available
```

### Tests

```text
test_edge_net_subtracts_all_costs
test_risk_engine_deny_by_default
test_low_liquidity_refused
test_edge_remaining_too_low
test_loss_halt_blocks_new_intent
test_circuit_breaker_blocks_after_cluster
test_depth_guard_before_paper_intent
```

---

## V11.11 — Taxonomie NO_TRADE enrichie

Ajouter en plus de la V10 :

```text
DATA_NOT_PAGINATED_ENOUGH
BACKFILL_INCOMPLETE
SOURCE_NOT_AUTHENTICATED_PUBLIC_ONLY
PROXY_POOL_DEGRADED
FETCH_PROVENANCE_MISSING
RAW_HASH_MISSING
FEATURE_HASH_MISSING
WALLET_EVIDENCE_TOO_LOW
COPY_DELAY_TOO_HIGH
EXIT_NOT_FOLLOWABLE
QUEUE_PROBABILITY_TOO_LOW
MAKER_REBATE_UNAVAILABLE
FUNDING_UNKNOWN
LEVERAGE_RISK_TOO_HIGH
MARGIN_RISK_TOO_HIGH
CLUSTER_TOO_CROWDED
CORRELATION_TOO_HIGH
STRATEGY_SHADOW_ONLY
MODEL_NOT_CALIBRATED
```

Chaque NO_TRADE doit avoir :

```text
reason_code
severity
is_retriable
missing_data
next_action
evidence_refs
dashboard_message
```

---

## V11.12 — PaperEngine simulation profonde

### Modules

```text
paper_trading/paper_engine.py
paper_trading/exec_model.py
paper_trading/exec_layer.py
paper_trading/dry_run_order.py
paper_trading/order_builder_sim.py
paper_trading/signature_sim.py
paper_trading/queue_model.py
paper_trading/maker_rebate_model.py
paper_trading/latency_model.py
paper_trading/slippage_model.py
paper_trading/funding_model.py
paper_trading/liquidation_model.py
paper_trading/sl_tp.py
paper_trading/journal.py
paper_trading/position_tracking.py
paper_trading/cost_accounting.py
paper_trading/exit_engine.py
```

### Actions paper

```text
BUILD_ORDER_SIM
SIGN_ORDER_SIM
OPEN_MARKET_SIM
OPEN_LIMIT_SIM
ADD_SIM
REDUCE_SIM
CLOSE_SIM
CANCEL_SIM_LOCAL_ONLY
TP_SIM
SL_SIM
TRAILING_STOP_SIM
LIQUIDATION_SIM
MISSED_FILL_SIM
PARTIAL_FILL_SIM
```

### Chaque action doit porter

```text
simulation_only=true
not_an_order=true
external_action=false
context
decision_id
evidence_chain_id
cost_breakdown
fill_probability
queue_position_estimate
resulting_position
realized_pnl_delta
unrealized_pnl_after
equity_after
```

### Tests

```text
test_paper_order_build_does_not_send
test_signature_sim_never_uses_private_key
test_queue_model_changes_fill_probability
test_maker_rebate_model
test_slippage_model_l2_depth
test_partial_fill_updates_position
test_reduce_close_realized_pnl
test_liquidation_sim_marks_risk_event
```

---

## V11.13 — Backtest / replay / optimisation

### Modules

```text
backtesting/data_bus.py
backtesting/materialized_cache.py
backtesting/ledger_replay.py
backtesting/book_replay.py
backtesting/trade_tick_replay.py
backtesting/experiment.py
backtesting/runner_contract.py
backtesting/multi_wallet_replay.py
backtesting/walk_forward.py
backtesting/optimize.py
backtesting/report_charts.py
backtesting/strategies/replicate_balance.py
backtesting/strategies/fade_impulse.py
```

### Règles anti-triche

- pas de lookahead ;
- décision à T ne voit que données <= T ;
- PnL BACKTEST séparé de LIVE ;
- TEST_FIXTURE séparé ;
- optimisation jamais sur runtime live ;
- walk-forward obligatoire pour modèle promu.

### Metrics

```text
total_return
realized_pnl
unrealized_pnl
equity_curve
drawdown_curve
max_drawdown
sharpe
sortino
calmar
winrate
profit_factor
brier_score
brier_advantage
fees
rebates
slippage
latency_cost
missed_fills
partial_fills
no_trade_distribution
copy_fidelity
execution_quality
```

### Tests

```text
test_backtest_no_lookahead
test_backtest_live_parity
test_experiment_runner_contract
test_walk_forward_splits
test_optuna_or_tpe_never_touches_live_runtime
test_report_has_all_metrics
```

---

## V11.14 — Dashboard produit final

### Pages

```text
Overview
Scanner
Source Registry
Proxy Health
REST Budget
WebSocket Status
Wallet Discovery
Watchlists
Shortlist
Wallet Leaderboard
Wallet Detail
Smart Money Filters
Labels & Red Flags
Pattern Detector
Cluster Detector
Market Features
Orderbook Imbalance
Microstructure
Volatility
Signals
NO_TRADE Explorer
Decision Ledger
Evidence Chain
Paper Portfolio
Paper Positions
Paper Trades
Paper Execution Model
Copy Fidelity
Execution Quality
Backtests
Replay
Optimization
Calibration
Risk Panel
Artifacts
Search
Doctor
Secure
Safety Audit
Data Sources
```

### Charts

```text
equity
realized_pnl
unrealized_pnl
drawdown
candles
spread
liquidity
depth
orderbook imbalance
edge net
copy degradation
latency
source health
wallet score
copyability
position markers
no_trade markers
backtest comparison
```

### Tests

```text
test_dashboard_empty_state_honest
test_dashboard_uses_only_db_or_exports
test_no_fake_chart_points
test_position_markers_match_paper_journal
test_no_trade_explorer_filters_reasons
test_dashboard_routes_do_not_send_external_actions
```

---

## V11.15 — CLI / Agent tools / MCP

### Commandes souhaitées

```text
hypersmart scan
hypersmart collect
hypersmart ws
hypersmart score-wallets
hypersmart run-paper
hypersmart replay
hypersmart backtest
hypersmart optimize
hypersmart dashboard
hypersmart export
hypersmart doctor
hypersmart secure
hypersmart safety-audit
hypersmart archive-clean
hypersmart research-rescan
```

### Agent tools

```text
status.read
source_health.read
wallet.leaderboard
wallet.detail
market.features.read
decision_ledger.search
evidence_chain.read
paper_portfolio.read
paper_trade.search
backtest.report.read
dashboard.export
research.rescan_sources
simulation.start_local
simulation.stop_local
paper_position.close_local
archive.create_clean
```

Tous les tools qui écrivent doivent être **local-only**.

Tests :

```text
test_agent_tool_schema_validation
test_agent_write_tools_local_only
test_mcp_no_real_action
test_cli_commands_available
```

---

## V11.16 — QA, release, archive

### Modules

```text
audit/safety_audit.py
audit/context_classifier.py
audit/no_real_action_scanner.py
audit/fake_data_scanner.py
archive/clean_archive.py
archive/sqlite_backup.py
release/readiness.py
```

### Audits

- pas d'action argent réel ;
- pas de private key ;
- pas de signature réelle ;
- pas de données fake dans dashboard ;
- contexte de mots sensibles classifié correctement ;
- DB runtime hors archive ;
- logs sans secrets ;
- docs cohérentes.

Tests :

```text
test_audit_allows_simulation_terms
test_audit_flags_real_external_action
test_fake_data_scanner_blocks_dashboard_fake
test_clean_archive_excludes_runtime_db
test_sqlite_backup_before_archive
test_release_readiness_report
```

---

## V11.17 — Ordre recommandé pour atteindre un logiciel "parfait"

### Bloc A — Fondation robuste
SourceRegistry, RunContext, SQLite migrations, SourceHealth, provenance, dedupe.

### Bloc B — Collecte grande échelle
Hyperliquid `/info`, WS, scraping public, proxy pool, weight budget, cache.

### Bloc C — Normalisation et lifecycle
NormalizedFill, position lifecycle, leader deltas, reconcile.

### Bloc D — Features et edge
Market features 70+, OBI, CVD, VWAP, vol, fair value, edge net.

### Bloc E — Wallet intelligence
Smart money, labels, pattern detector, cluster detector, copyability.

### Bloc F — Décision
RiskEngine, NO_TRADE taxonomy, EvidenceChain.

### Bloc G — Simulation profonde
PaperEngine, dry-run order, queue, fees, rebates, slippage, funding, exits.

### Bloc H — Backtest/replay
Ledger replay, book replay, walk-forward, optimization.

### Bloc I — Produit
Dashboard, charts, API, CLI, MCP, artifacts, search.

### Bloc J — QA
Safety audit, fake data scanner, clean archive, release readiness.

---

## V11.18 — Objectif Codex recommandé

```text
Lis AGENTS.md puis docs/HYPERSMART_FUSION_ROADMAP_V11.md. Travaille local only dans C:\Users\flo\Desktop\Projet invest. Ne supprime rien. Applique V11 par gros blocs jusqu'au maximum possible: fondation, collecte, WS, normalisation, lifecycle, features, scoring, décision, PaperEngine simulation profonde, backtest, dashboard, agent tools, QA. Tout concept des 14 GitHub est autorisé en recherche/read-only/simulation locale/outils locaux; seule limite: aucune action argent-réel externe et aucune donnée fabriquée. Code réel, tests, safety-audit, rapport FR, fichier de reprise si incomplet.
```

---

## V11.19 — Phrase finale pour agents

> Construire HyperSmart comme fusion complète des 14 GitHub, en Hyperliquid par défaut, simulation paper locale, données réelles uniquement, aucune action argent-réel externe, aucune donnée fabriquée, tous les modules testés, toutes les idées tracées.


---

# HYPERSMART OBSERVER — FEUILLE DE ROUTE FUSIONNÉE V12
## Manuel d'exécution ultra-explicatif pour agent IA autonome
### "Quoi coder, pourquoi le coder, où le coder, comment le tester, comment savoir que c'est terminé"

> **Cette V12 ne supprime rien de la V9/V10/V11.**  
> Elle ajoute une couche explicative. Les anciennes feuilles de route disaient souvent "code tel module". La V12 explique maintenant ce que chaque module veut dire, ce qu'il reçoit, ce qu'il produit, les erreurs à gérer, les réglages à prévoir, les tests à écrire, et comment un agent IA doit avancer sans se perdre.
>
> Objectif final : construire HyperSmart comme une fusion complète des idées des 14 GitHub, mais avec une destination unique : **Hyperliquid par défaut, simulation paper locale, vraie donnée uniquement, aucune action argent-réel externe.**

---

## V12.0 — Règle de lecture pour Claude/Codex

Un agent doit lire cette V12 comme un **manuel de construction**, pas comme une wishlist.

Pour chaque section, l'agent doit se poser ces questions :

1. Est-ce que cette capacité existe déjà dans le code ?
2. Si oui, est-elle complète, testée, branchée au dashboard et au backtest ?
3. Si elle est partielle, quel morceau manque ?
4. Si elle est absente, quelle vertical slice minimale prouve qu'elle fonctionne ?
5. Quel test prouve qu'elle ne crée pas de faux PnL, faux trade ou action réelle ?
6. Quel export/dashboard prouve que l'utilisateur peut vérifier le résultat ?

Un agent ne doit pas dire "DONE" parce qu'un fichier existe.  
Une capacité est DONE seulement si elle a :

```text
code réel
tests
source de données réelle ou fixture claire
no fake
no real external action
dashboard/export ou rapport
documentation courte
```

---

## V12.1 — Glossaire opérationnel

### HyperSmart

Logiciel local d'observation et de simulation. Il lit Hyperliquid, analyse les wallets, détecte des signaux, simule ce qu'on aurait fait, calcule le PnL paper, et explique chaque décision.

### Source réelle

Donnée qui vient de :

- Hyperliquid `/info`;
- Hyperliquid WebSocket;
- page publique lue par scraper;
- GitHub public;
- fichier fourni par l'utilisateur;
- dataset historique public;
- cache local dont la provenance est traçable.

### Donnée fake

Donnée inventée pour remplir un écran ou faire croire qu'un trade existe. Interdit.  
Une fixture de test est autorisée si elle reste dans `tests/fixtures` ou `TEST_FIXTURE`.

### Paper trade

Action locale simulée. Ce n'est pas un ordre. Un paper trade doit porter :

```text
simulation_only=true
not_an_order=true
external_action=false
```

### Signal

Indice exploitable, pas une décision. Un signal doit passer par RiskEngine.

### Score

Classement d'un wallet ou d'une opportunité. Un score n'est jamais suffisant pour ouvrir en paper.

### Decision

Résultat du moteur après RiskEngine :

```text
NO_TRADE
PAPER_INTENT
PAPER_EXIT
PAPER_REJECTED
```

### Evidence

Tout ce qui prouve une décision : raw refs, source health, feature hash, fill hash, reason codes, PnL state, config active.

---

## V12.2 — Architecture finale racontée simplement

HyperSmart doit fonctionner comme une usine en 12 étages.

### Étage 1 — Source Registry

But : savoir d'où viennent les données.

L'agent doit créer un registre qui liste toutes les sources : Hyperliquid `/info`, WS, pages publiques, GitHub, fichiers utilisateur, datasets, caches.

Sans Source Registry, on ne sait pas si une donnée est vraie, fraîche, vieille, cachée ou douteuse.

### Étage 2 — Collecte

But : récupérer le maximum de données utiles.

La collecte doit combiner :

- REST `/info`;
- WebSocket;
- scraping public;
- imports fichiers;
- bulk historique;
- cache local;
- proxy pool si configuré.

### Étage 3 — Raw Store

But : garder la donnée brute avant transformation.

Pourquoi : si un score ou PnL semble faux, on doit pouvoir revenir à la donnée originale.

### Étage 4 — Normalisation

But : transformer les formats externes en modèles internes propres.

Exemple : un fill Hyperliquid devient `NormalizedFill`.

### Étage 5 — Source Health

But : savoir si la donnée est fraîche, fiable, complète.

Si la source est mauvaise, on ne fabrique pas. On dégrade et on refuse.

### Étage 6 — Position Lifecycle

But : comprendre ce qu'un wallet a vraiment fait.

Le moteur doit dire : OPEN, ADD, INCREASE, REDUCE, CLOSE, FLIP, UNKNOWN.

### Étage 7 — Market Features

But : comprendre le marché autour du signal.

Spread, liquidité, orderbook imbalance, microprice, VWAP, CVD, volatility, edge, depth.

### Étage 8 — Wallet Intelligence

But : savoir quels wallets valent la peine d'être suivis.

Smart money, copyability, red flags, patterns, consistency, PnL concentration, drawdown.

### Étage 9 — Signal + Risk

But : décider si la simulation doit faire quelque chose.

Tout passe par RiskEngine. Par défaut : NO_TRADE.

### Étage 10 — PaperEngine

But : simuler comme si on s'était placé en réel, mais sans jamais envoyer un ordre.

Inclure coûts, queue, latency, spread, slippage, fill probability, maker/taker, TP/SL, exits.

### Étage 11 — Evidence + Backtest

But : prouver et rejouer.

Chaque décision doit être vérifiable. Chaque stratégie doit être rejouable sans lookahead.

### Étage 12 — Dashboard

But : rendre tout lisible.

L'utilisateur doit voir pourquoi le bot attend, pourquoi il refuse, ce qu'il aurait fait, combien la simulation gagne/perd, et quelles sources sont fiables.

---

# PARTIE A — MODULES À CODER EN DÉTAIL

---

## A1 — `sources/registry.py` — Source Registry

### Ce que c'est

Un catalogue local de toutes les sources de données que HyperSmart peut lire.  
C'est la carte d'identité des sources. Sans lui, un agent ne sait pas si une donnée vient d'Hyperliquid, d'un scraper, d'une fixture, d'un vieux cache ou d'un fichier importé.

### Pourquoi c'est important

- éviter les données fantômes ;
- tracer la provenance ;
- savoir quoi rafraîchir ;
- savoir quelle source est autorisée dans LIVE, BACKTEST, REPLAY ou TEST_FIXTURE ;
- permettre au dashboard d'afficher "source OK" ou "source stale".

### À coder

Créer :

```text
hyper_smart_observer/sources/registry.py
hyper_smart_observer/sources/models.py
hyper_smart_observer/sources/provenance.py
```

### Modèle `SourceDefinition`

```python
@dataclass
class SourceDefinition:
    source_id: str
    name: str
    kind: Literal[
        "HYPERLIQUID_INFO",
        "HYPERLIQUID_WS",
        "PUBLIC_HTML",
        "PUBLIC_API",
        "GITHUB",
        "USER_FILE",
        "BULK_S3",
        "LOCAL_CACHE",
    ]
    url_or_endpoint: str
    enabled: bool
    read_only: bool
    requires_login: bool
    requires_secret: bool
    allowed_contexts: set[str]
    cache_ttl_seconds: int
    rate_limit_policy_id: str | None
    proxy_policy_id: str | None
    notes: str | None
```

### Modèle `FetchProvenance`

```python
@dataclass
class FetchProvenance:
    fetch_id: str
    source_id: str
    url_or_endpoint: str
    method: str
    status_code: int | None
    fetched_at_ms: int
    latency_ms: float | None
    proxy_id: str | None
    cache_hit: bool
    raw_hash: str
    parsed_hash: str | None
    parser_version: str | None
    data_quality: str
```

### Algorithme

1. Charger les sources depuis config + defaults.
2. Refuser toute source marquée `requires_secret=True` dans les workflows research/scraping public.
3. Pour chaque fetch, créer un `FetchProvenance`.
4. Stocker provenance dans SQLite.
5. Lier toute donnée normalisée à `fetch_id` ou `source_health_id`.

### Réglages

```text
HYPERSMART_SOURCE_REGISTRY_PATH=config/sources.toml
HYPERSMART_PUBLIC_SCRAPER_ENABLED=1
HYPERSMART_GITHUB_RESEARCH_ENABLED=1
HYPERSMART_FETCH_CACHE_TTL_SEC=30
```

### Tests

```text
test_source_registry_registers_hyperliquid_info
test_source_registry_registers_public_html
test_source_registry_blocks_secret_required_source_in_public_mode
test_fetch_provenance_hashes_raw_payload
test_every_normalized_event_has_source_ref
```

### Dashboard

Panel `Data Sources` :

- source name ;
- kind ;
- status ;
- last fetch ;
- latency ;
- quality ;
- latest error.

---

## A2 — `collection/proxy_pool.py` — Proxy Pool

### Ce que c'est

Un gestionnaire d'IP de sortie pour la collecte grande échelle. Il sert à répartir les requêtes, éviter de saturer une seule IP, maintenir un débit stable, et isoler les erreurs par proxy.

### Pourquoi c'est important

La V9 dit que scraping + proxy rotation sont des outils de première classe. Le proxy pool doit donc devenir un composant officiel de collecte, pas un bricolage.

### À coder

```text
hyper_smart_observer/collection/proxy_pool.py
hyper_smart_observer/collection/proxy_models.py
hyper_smart_observer/collection/proxy_health.py
```

### Modèle `ProxyEndpoint`

```python
@dataclass
class ProxyEndpoint:
    proxy_id: str
    url: str
    kind: Literal["HTTP", "HTTPS", "SOCKS5"]
    provider: str | None
    enabled: bool
    weight_budget_per_minute: int
    status: Literal["ACTIVE", "COOLDOWN", "RETIRED"]
    success_count: int
    error_count: int
    last_error: str | None
    avg_latency_ms: float | None
    cooldown_until_ms: int | None
```

### Stratégies

```text
STICKY_BY_SHARD
ROUND_ROBIN
PER_SESSION
DIRECT_NO_PROXY
```

### Algorithme sticky-by-shard

1. Calculer `shard_key = wallet` ou `coin`.
2. Hasher la clé.
3. Assigner à un proxy actif.
4. Garder la même assignation tant que le proxy est sain.
5. Si 429/403/timeout répété, passer en cooldown et basculer le shard.

### Réglages

```text
HYPERSMART_PROXY_POOL_ENABLED=0|1
HYPERSMART_PROXY_STRATEGY=STICKY_BY_SHARD
HYPERSMART_PROXY_COOLDOWN_BASE_SEC=30
HYPERSMART_PROXY_MAX_ERRORS_BEFORE_COOLDOWN=3
HYPERSMART_PROXY_WEIGHT_BUDGET_PER_MIN=1200
```

### Tests

```text
test_proxy_pool_selects_active_proxy
test_proxy_pool_sticky_sharding_same_wallet_same_proxy
test_proxy_rotation_on_429
test_proxy_cooldown_then_recover
test_proxy_pool_disabled_uses_direct_connection
```

### Dashboard

Panel `Proxy Health` :

- proxy_id ;
- status ;
- success/error ;
- 429/403 ;
- latency ;
- current shards ;
- cooldown.

---

## A3 — `collection/weight_budgeter.py` — Weight Budgeter

### Ce que c'est

Un compteur de budget de requêtes. Hyperliquid ne compte pas seulement "nombre de requêtes", mais des poids par endpoint et par taille de réponse. Le budgeter empêche de dépasser les limites et indique quand ralentir.

### À coder

```text
hyper_smart_observer/collection/weight_budgeter.py
hyper_smart_observer/hyperliquid_client/rate_weights.py
```

### Table de poids configurable

```python
INFO_WEIGHTS = {
    "allMids": 2,
    "l2Book": 2,
    "clearinghouseState": 2,
    "orderStatus": 2,
    "exchangeStatus": 2,
    "userRole": 60,
    "default": 20,
}
```

Ajouter poids additionnels pour :

- `userFills`;
- `userFillsByTime`;
- `recentTrades`;
- `candleSnapshot`.

### Algorithme

1. Avant chaque requête, estimer le poids.
2. Vérifier le budget du proxy ou direct egress.
3. Si budget insuffisant, retarder ou skip.
4. Après réponse, ajuster selon nombre d'items retournés.
5. Stocker `RateBudgetSnapshot`.

### Tests

```text
test_weight_budget_all_mids_is_2
test_weight_budget_default_info_is_20
test_weight_budget_user_fills_additional_items
test_budget_blocks_when_exhausted
test_budget_recovers_after_window
```

---

## A4 — `collection/html_scraper.py` — Public Scraper

### Ce que c'est

Un scraper pour pages publiques utiles : leaderboards, dashboards publics, docs, pages GitHub, exports HTML.

### Règles

- autorisé pour pages publiques ;
- pas de bypass login/captcha/paywall ;
- cache obligatoire ;
- provenance obligatoire ;
- parser versionné ;
- rate limit + backoff.

### Modules

```text
collection/html_scraper.py
collection/public_fetcher.py
collection/parsers/base.py
collection/parsers/github.py
collection/parsers/hyperliquid_public.py
```

### Output

```text
ScrapeResult:
  source_id
  url
  raw_html_hash
  parsed_items
  parser_version
  fetched_at
  provenance_id
  data_quality
```

### Tests

```text
test_html_scraper_reads_public_fixture
test_html_scraper_blocks_requires_login_source
test_html_scraper_uses_cache
test_html_scraper_records_provenance
test_html_scraper_never_creates_live_trade_signal_directly
```

---

## A5 — `hyperliquid_client/info_readonly.py`

### Ce que c'est

Le client officiel interne pour lire `/info`. Il doit être fin, testable et jamais mélangé avec l'exécution.

### Méthodes

```python
get_all_mids()
get_l2_book(coin)
get_candle_snapshot(coin, interval, start_time=None, end_time=None)
get_recent_trades(coin)
get_clearinghouse_state(wallet)
get_user_fills(wallet)
get_user_fills_by_time(wallet, start_time, end_time)
get_open_orders(wallet)
get_frontend_open_orders(wallet)
get_order_status(wallet, oid_or_cloid)
get_user_fees(wallet)
get_exchange_status()
```

### Règles

- uniquement POST `/info`;
- jamais `/exchange`;
- timeout configurable ;
- retry borné ;
- rate weight ;
- source health ;
- raw hash ;
- pagination ;
- aucune clé privée.

### Tests

```text
test_info_readonly_never_calls_exchange
test_info_readonly_records_raw_hash
test_info_readonly_updates_source_health
test_user_fills_by_time_paginates
test_candle_snapshot_returns_degraded_when_empty
```

---

## A6 — `realtime_monitor/ws_supervisor.py`

### Ce que c'est

Le superviseur temps réel. Il garde les connexions WebSocket ouvertes, gère snapshots, updates, reconnect, dedupe, gap recovery.

### Fonctions

```text
connect
subscribe
handle_snapshot
handle_update
dedupe_event
persist_event
detect_gap
rest_reconcile
heartbeat
reconnect_with_backoff
shutdown_cleanly
```

### Règles

- cap 10 users uniques ;
- séparer channels marché et user ;
- snapshot `isSnapshot:true` ne doit pas doubler les updates ;
- chaque event doit avoir raw_hash ;
- gap => REST reconcile ;
- fail => source health degraded ;
- durée bornée en test.

### Tests

```text
test_ws_snapshot_does_not_duplicate_updates
test_ws_reconnect_with_backoff
test_ws_gap_triggers_rest_reconcile
test_ws_cap_10_user_streams
test_ws_event_persisted_with_raw_hash
```

---

## A7 — `storage/sqlite_store.py` + migrations

### Ce que c'est

La base locale. Elle doit séparer raw, normalized, decisions, paper, backtest, dashboard.

### À coder

- migration runner ;
- idempotent upsert ;
- WAL ;
- unique constraints ;
- context isolation ;
- backup helper ;
- export helper.

### Tables critiques et pourquoi

#### `raw_events`

Garde la preuve brute. Sert à rejouer et débugger.

#### `fills_normalized`

Base du lifecycle.

#### `position_lifecycle_events`

Explique OPEN/ADD/REDUCE/CLOSE.

#### `leader_deltas`

Transforme lifecycle en opportunité.

#### `market_features`

Stocke l'état du marché utilisé pour décider.

#### `risk_decisions` / `no_trade_decisions`

Explique pourquoi on agit ou refuse.

#### `paper_trades` / `paper_positions`

Montre la simulation.

#### `evidence_chain`

Relie tout.

### Tests

```text
test_migrations_run_twice
test_unique_fill_hash
test_context_isolation_live_backtest
test_sqlite_backup_creates_consistent_copy
```

---

## A8 — `normalization/fills.py`

### Ce que c'est

Convertit les fills Hyperliquid en format interne.

### Champs Hyperliquid importants

```text
coin
px
sz
side
time
startPosition
dir
closedPnl
hash
oid
tid
fee
feeToken
crossed
liquidation
builderFee
```

### Erreurs à gérer

- champ manquant ;
- px non numérique ;
- size 0 ;
- time futur ;
- duplicate hash ;
- liquidation spéciale ;
- fee manquante.

### Tests

```text
test_fill_normalization_full_fields
test_fill_missing_price_rejected
test_duplicate_fill_hash_ignored
test_future_timestamp_degraded
test_liquidation_fill_flagged
```

---

## A9 — `position_lifecycle/reconstructor.py`

### Ce que c'est

Le cerveau qui reconstitue ce qu'un leader fait.

### Logique

1. Trier fills par wallet, coin, temps, tid.
2. Lire `startPosition`.
3. Estimer position avant/après.
4. Utiliser `dir` et `closedPnl`.
5. Grouper fills proches du même oid.
6. Classer l'événement :
   - open ;
   - add/increase ;
   - reduce ;
   - close ;
   - flip ;
   - liquidation ;
   - unknown.
7. Calculer confidence.
8. Émettre NoTrade si ambigu.

### Tests obligatoires

```text
test_lifecycle_open_long_from_zero
test_lifecycle_add_long_from_positive
test_lifecycle_reduce_long_closed_pnl_present
test_lifecycle_close_long_to_zero
test_lifecycle_flip_long_to_short
test_lifecycle_partial_close_multiple_fills
test_lifecycle_liquidation_event
test_lifecycle_unknown_when_start_position_missing
```

---

## A10 — `signals/leader_delta.py`

### Ce que c'est

Un lifecycle event n'est pas encore un signal. LeaderDelta est la traduction : "ce wallet vient d'ouvrir/réduire/fermer telle position".

### Algorithme

1. Recevoir `PositionLifecycleEvent`.
2. Si event_type UNKNOWN => NoTrade.
3. Si OPEN/ADD/INCREASE => créer `SignalCandidate`.
4. Si REDUCE/CLOSE/FLIP => envoyer à `ExitEngine`.
5. Calculer signal age.
6. Appliquer freshness decay.
7. Lier evidence refs.

### Tests

```text
test_open_lifecycle_to_signal_candidate
test_close_lifecycle_to_exit_request
test_unknown_lifecycle_to_no_trade
test_signal_age_decay
test_leader_delta_has_evidence_refs
```

---

## A11 — `features/scan_features_schema.py`

### Ce que c'est

Le schéma complet des features de scan. C'est l'équivalent polyrec 70+ colonnes, adapté Hyperliquid.

### Catégories de colonnes

1. identité run ;
2. source/provenance ;
3. wallet ;
4. coin ;
5. lifecycle ;
6. prix/mids ;
7. carnet ;
8. microstructure ;
9. trades ;
10. candles ;
11. volatilité ;
12. edge ;
13. risk ;
14. décision ;
15. paper.

### Tests

```text
test_scan_features_schema_has_required_categories
test_scan_features_minimum_70_columns
test_scan_features_csv_json_same_columns
```

---

## A12 — `features/microstructure.py`

### Ce que c'est

Analyse fine du marché.

### Fonctions

```text
compute_orderbook_imbalance
compute_microprice
compute_depth_slope
compute_trade_flow_delta
compute_cvd
compute_vwap
compute_rvol
compute_impulse
compute_basis
compute_liquidation_score
```

### Règles

- si trades absents -> None/degraded ;
- si l2Book absent -> no book features ;
- zéro division protégée ;
- source_health propagée.

### Tests

```text
test_orderbook_imbalance
test_microprice
test_depth_slope
test_cvd
test_vwap_requires_trades
test_missing_book_degraded
```

---

## A13 — `edge/edge_calculator.py`

### Ce que c'est

Calcule si copier a encore un edge après tous les coûts.

### Formule

```text
net_edge_bps =
gross_edge_bps
- fees_bps
- spread_cost_bps
- slippage_bps
- latency_penalty_bps
- copy_degradation_bps
- volatility_penalty_bps
- liquidity_penalty_bps
- funding_estimate_bps
```

### Inputs requis

- leader reference price ;
- current mid ;
- spread ;
- l2 depth ;
- fees ;
- volatility ;
- signal age ;
- latency estimate.

### Sorties

```text
EdgeEstimate:
  gross_edge_bps
  total_costs_bps
  net_edge_bps
  threshold_bps
  is_positive
  unmeasurable_reason
```

### Tests

```text
test_net_edge_subtracts_all_costs
test_edge_unmeasurable_without_current_mid
test_edge_unmeasurable_without_leader_price
test_edge_negative_after_latency
test_edge_positive_allows_risk_eval
```

---

## A14 — `risk/risk_engine.py`

### Ce que c'est

Le gardien central. Il décide si un signal peut devenir une action paper locale.

### Gates

```text
source health
wallet score
copyability
lifecycle confidence
freshness
spread
depth
liquidity
volatility
edge net
cooldown
portfolio exposure
loss halts
circuit breaker
duplicate guard
paper engine modelable
evidence available
```

### Règle

Deny by default. Un signal doit prouver qu'il est simulable.

### Output

```text
RiskDecision:
  allowed
  decision_type
  reason_codes
  severity
  sizing
  evidence_refs
```

### Tests

```text
test_risk_deny_by_default
test_each_gate_can_block
test_multiple_reasons_preserved
test_allowed_signal_has_sizing_and_evidence
```

---

## A15 — `paper_trading/exec_model.py`

### Ce que c'est

Le modèle qui simule comment l'ordre aurait été exécuté.

### Composants

```text
fee_model
maker_rebate_model
spread_model
slippage_model
latency_model
queue_model
partial_fill_model
missed_fill_model
funding_model
liquidation_model
```

### Pourquoi

Sans exec model, le PnL paper est trop optimiste. Le but est de simuler "si on s'était placé en réel", avec coûts réalistes.

### Tests

```text
test_fee_model
test_maker_rebate_model
test_slippage_grows_when_depth_low
test_latency_moves_fill_price
test_queue_probability_can_miss_fill
test_partial_fill_reduces_size
```

---

## A16 — `paper_trading/paper_engine.py`

### Ce que c'est

Le moteur de simulation local. Il applique PaperIntent et PaperExit.

### Actions

```text
open_market_sim
open_limit_sim
add_sim
reduce_sim
close_sim
cancel_local_sim
tp_sim
sl_sim
trailing_stop_sim
liquidation_sim
mark_to_market
```

### Règles

- ne jamais appeler API externe ;
- ne jamais utiliser private key ;
- tout action porte `not_an_order=true`;
- PnL latent seulement si mid réel ;
- equity = starting + realized + unrealized ;
- drawdown depuis peak equity ;
- contexte séparé LIVE/BACKTEST/REPLAY.

### Tests

```text
test_paper_open_local_only
test_paper_reduce_local_only
test_paper_close_local_only
test_pnl_long_short
test_unrealized_requires_real_mid
test_drawdown_from_equity_curve
test_no_external_action_from_paper_engine
```

---

## A17 — `paper_trading/exit_engine.py`

### Ce que c'est

Le moteur de sortie. Il ferme/réduit paper quand le leader ferme/réduit ou quand les stops se déclenchent.

### Sources d'exit

- leader reduce ;
- leader close ;
- leader flip ;
- time stop ;
- trailing stop ;
- max MAE ;
- TP/SL ;
- stale source ;
- risk halt ;
- max holding time.

### Tests

```text
test_leader_reduce_reduces_paper_position
test_leader_close_closes_paper_position
test_no_matching_paper_position_no_trade
test_trailing_stop_closes_local_position
test_time_stop_closes_local_position
test_exit_updates_realized_pnl
```

---

## A18 — `evidence/decision_ledger.py`

### Ce que c'est

Le registre de vérité. Chaque décision doit être auditable.

### Tables

```text
decision_ledger
evidence_chain
journal_append_only
block_reason_stats
```

### Champs `DecisionLedgerEntry`

```text
decision_id
run_id
context
wallet
coin
decision_type
reason_codes
risk_decision_id
signal_candidate_id
paper_action_id
feature_hash
source_health_refs
created_at
stable_hash
```

### Tests

```text
test_no_trade_has_evidence_chain
test_paper_intent_has_evidence_chain
test_paper_exit_has_evidence_chain
test_decision_hash_stable
test_tamper_changes_hash
test_block_reason_stats_count_reasons
```

---

## A19 — `backtesting/experiment.py`

### Ce que c'est

Un cadre pour lancer des expériences reproductibles.

### Objet `Experiment`

```text
experiment_id
name
hypothesis
wallets
coins
date_range
strategy
parameters
data_sources
cost_model
delay_model
risk_config
expected_outputs
```

### Règles

- pas de lookahead ;
- même RiskEngine que runtime ;
- même PaperEngine que runtime ;
- contexte BACKTEST séparé ;
- report complet.

### Tests

```text
test_experiment_contract
test_backtest_no_lookahead
test_runtime_backtest_same_decisions_on_same_events
test_walk_forward_splits
test_optimization_does_not_use_live_context
```

---

## A20 — `ui/dashboard` et charts

### Ce que c'est

Le produit visible. Il doit montrer la vérité, pas juste être joli.

### Principe

Chaque chiffre affiché doit venir :

- de SQLite ;
- d'un export ;
- d'un source_health ;
- d'un backtest report ;
- d'une fixture de test uniquement en mode test.

### Pages détaillées

#### Overview

- runtime mode ;
- total paper equity ;
- PnL realized/unrealized ;
- drawdown ;
- active sources ;
- no_trade ratio ;
- last scan.

#### Scanner

- wallets scannés ;
- proxy budget ;
- REST budget ;
- WS status ;
- failures.

#### Wallet Detail

- score ;
- copyability ;
- fills ;
- lifecycle ;
- patterns ;
- red flags.

#### Decisions

- all decisions ;
- filters by reason ;
- evidence chain ;
- feature hash ;
- raw refs.

#### Paper Portfolio

- positions ;
- actions ;
- PnL ;
- costs ;
- exit reason.

#### Backtest

- experiments ;
- replay timeline ;
- metrics ;
- comparison chart.

### Tests

```text
test_dashboard_empty_state
test_dashboard_overview_real_values
test_dashboard_decision_links_evidence
test_dashboard_paper_portfolio_matches_db
test_dashboard_chart_no_fake_points
```

---

## A21 — `agent_tools` et MCP

### Ce que c'est

Une interface pour que Claude/Codex/Jules puissent lire et piloter localement sans action externe.

### Tools read

```text
status.read
source_health.read
wallet.leaderboard
wallet.detail
market.features.read
decision_ledger.search
evidence_chain.read
paper_portfolio.read
paper_trade.search
backtest.report.read
dashboard.export
```

### Tools local write

```text
research.rescan_sources
simulation.start_local
simulation.stop_local
paper_position.close_local
backtest.run
archive.create_clean
```

### Règles

- local only ;
- pas de clé ;
- pas d'ordre réel ;
- schemas JSON ;
- limites de résultats ;
- erreurs propres.

### Tests

```text
test_agent_tools_schema_valid
test_agent_tools_read_do_not_mutate
test_agent_tools_write_local_only
test_mcp_no_external_action
```

---

## A22 — `audit/context_classifier.py`

### Ce que c'est

Un audit intelligent qui ne bloque pas un mot, mais son contexte.

### Catégories

```text
DOC_ONLY
TEST_ONLY
SIMULATION_ONLY
LOCAL_TOOL
READ_ONLY_RESEARCH
DANGEROUS_EXTERNAL_ACTION
```

### Exemple

`buy` dans `paper_engine.py` = simulation OK.  
`buy` dans un HTTP POST vers un endpoint externe = danger.  
`Polymarket` dans docs = recherche OK.  
`private_key` dans test d'audit = test OK.  
`private_key` dans runtime actif = danger.

### Tests

```text
test_audit_allows_simulation_buy_sell
test_audit_allows_polymarket_research_docs
test_audit_flags_external_order_post
test_audit_flags_private_key_runtime
test_audit_context_classifier
```

---

# PARTIE B — GRANDS BLOCS EXÉCUTABLES

## Bloc 1 — Fondation

Objectif : rendre le projet traçable.

À faire :

1. SourceRegistry.
2. FetchProvenance.
3. SourceHealth.
4. SQLite migrations.
5. RunContext.
6. RawStore.
7. Dedupe.

Livrable :

- collecte basique traçable ;
- aucune donnée perdue ;
- tests idempotence.

## Bloc 2 — Collecte

Objectif : alimenter le moteur.

À faire :

1. Hyperliquid info client.
2. WS supervisor.
3. Public scraper.
4. Proxy pool.
5. Weight budgeter.
6. Cache.
7. Reconciliation.

Livrable :

- scan wallets/coins ;
- source health ;
- backfill paginé ;
- WS stable.

## Bloc 3 — Compréhension

Objectif : comprendre les wallets et le marché.

À faire :

1. NormalizedFill.
2. PositionLifecycle.
3. LeaderDelta.
4. MarketFeatures 70+.
5. WalletScore.
6. Copyability.
7. Patterns.

Livrable :

- un leader est compris ;
- un signal peut être expliqué.

## Bloc 4 — Décision

Objectif : refuser mieux et agir seulement quand simulable.

À faire :

1. EdgeNet.
2. RiskEngine.
3. NO_TRADE taxonomy.
4. EvidenceChain.

Livrable :

- chaque décision est prouvée.

## Bloc 5 — Simulation

Objectif : savoir si ça gagne/perd.

À faire :

1. PaperEngine.
2. ExecModel.
3. QueueModel.
4. ExitEngine.
5. PnL/equity/drawdown.

Livrable :

- simulation crédible.

## Bloc 6 — Backtest

Objectif : tester sur historique sans triche.

À faire :

1. LedgerReplay.
2. BookReplay.
3. Experiment.
4. WalkForward.
5. Optimization.

Livrable :

- rapport de performance.

## Bloc 7 — Produit

Objectif : rendre le logiciel utilisable.

À faire :

1. Dashboard.
2. Charts.
3. API latest.
4. CLI.
5. Agent tools.
6. Artifacts.
7. Search.

Livrable :

- cockpit complet.

## Bloc 8 — QA

Objectif : empêcher les régressions.

À faire :

1. Safety audit.
2. Fake data scanner.
3. Archive clean.
4. Release readiness.
5. Coverage matrix.

Livrable :

- prêt pour développement long terme.

---

# PARTIE C — MATRICE DE RÉGLAGES À PRÉVOIR

```text
HYPERSMART_MODE=PAPER
HYPERSMART_CONTEXT=LIVE|BACKTEST|REPLAY|TEST_FIXTURE
HYPERSMART_STARTING_EQUITY=1000
HYPERSMART_MAX_SIGNAL_AGE_MS=6000
HYPERSMART_MIN_EDGE_BPS=35
HYPERSMART_MIN_LIQUIDITY_SCORE=0.5
HYPERSMART_MAX_COPY_DEGRADATION_BPS=12
HYPERSMART_MAX_SPREAD_BPS=500
HYPERSMART_MIN_DEPTH_USD=200
HYPERSMART_MAX_OPEN_POSITIONS=...
HYPERSMART_MAX_POSITION_NOTIONAL=...
HYPERSMART_DAILY_LOSS_HALT_PCT=5
HYPERSMART_MONTHLY_LOSS_HALT_PCT=15
HYPERSMART_DRAWDOWN_HALT_PCT=25
HYPERSMART_TOTAL_LOSS_HALT_PCT=40
HYPERSMART_PROXY_POOL_ENABLED=0|1
HYPERSMART_PUBLIC_SCRAPER_ENABLED=1
HYPERSMART_WS_MAX_USER_STREAMS=10
HYPERSMART_FEATURES_TOPN_L2=10
HYPERSMART_BACKTEST_NO_LOOKAHEAD=1
HYPERSMART_DASHBOARD_NO_FAKE=1
```

---

# PARTIE D — DEFINITION OF DONE FINALE

Le logiciel est considéré avancé correctement seulement si :

```text
source registry existe
collecte fonctionne
source health visible
raw store existe
normalisation testée
lifecycle reconstruit
leader delta généré
features marché calculées
wallet score calculé
copyability calculée
risk engine refuse par défaut
NO_TRADE expliqué
PaperEngine ouvre/réduit/ferme localement
PnL/equity/drawdown calculés
EvidenceChain complète
Backtest sans lookahead
Dashboard sans fake
Agent tools local-only
Safety audit context-aware
aucune action argent réel
aucune donnée fabriquée
```

---

# PARTIE E — OBJECTIF CODEX RECOMMANDÉ

```text
Lis AGENTS.md puis docs/HYPERSMART_FUSION_ROADMAP_V12.md. Travaille local only dans C:\Users\flo\Desktop\Projet invest. Ne supprime rien. Applique la V12 comme manuel de construction: fondation, collecte, normalisation, lifecycle, features, wallet intelligence, décision, PaperEngine simulation profonde, backtest, dashboard, agent tools, QA. Tout concept des 14 GitHub est autorisé en recherche/read-only/simulation locale/outils locaux. Seules limites: aucune action argent-réel externe, aucune donnée fabriquée. Code réel, tests, safety-audit, rapport FR, fichier de reprise si incomplet.
```

---

# PARTIE F — PHRASE DE CONTRÔLE

> Si une fonctionnalité ne peut pas prouver sa donnée, son coût, son effet sur le PnL paper et son absence d'action réelle, elle n'est pas terminée.

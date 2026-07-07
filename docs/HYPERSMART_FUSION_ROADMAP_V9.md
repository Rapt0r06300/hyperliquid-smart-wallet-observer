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

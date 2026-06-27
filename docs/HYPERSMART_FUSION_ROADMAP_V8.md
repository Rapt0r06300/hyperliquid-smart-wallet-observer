# HYPERSMART_FUSION_ROADMAP_V8 — Feuille de route fusionnée (14 GitHub → Hyperliquid paper)

> **But du document.** Fusionner *toutes* les bonnes idées des 14 dépôts GitHub fournis en une seule feuille de route exécutable, pour faire de **HyperSmart Observer** un bot de **copy-trade / smart-wallet observer** quasi parfait — **en simulation paper, branché sur les données réelles Hyperliquid (read-only)**, prêt à passer en réel plus tard sans réécriture.
>
> **Date :** 2026-06-19 · **Statut :** plan vivant · **Cible runtime :** Hyperliquid (`/info` + WebSocket public, read-only).
>
> **Relation avec l'existant.** Ce document **ne remplace pas** `CODEX_HYPERSMART_MASTER_PLAN_V7_ACTION_BOUNDARY.md` ni la V6. Il les **consolide** : la doctrine de sécurité reste la V7 (seule interdiction dure = action réelle externe). V8 ré-ordonne tout en **slices verticales livrables**, ajoute les formules manquantes (score wallet, edge net, copy-degradation), et relie chaque idée à un **module existant** de `hyper_smart_observer/`.

---

## 0. TL;DR — la thèse en 8 lignes

1. **HyperSmart n'est pas un bot d'exécution. C'est un observateur + simulateur.** Il regarde des wallets Hyperliquid via données publiques, reconstruit leurs positions, score leur « copiabilité », et **rejoue en paper** ce qu'un copieur ferait — avec frais, spread, slippage, latence et dégradation de copie réalistes.
2. **Moins de trades, mais beaucoup plus propres.** Le cœur du logiciel est un **filtre NO_TRADE deny-by-default**, pas un générateur d'entrées.
3. **Un seul cœur d'observation/paper + une seule couche de risque + des adapters read-only** (Hyperliquid live, Mock, dYdX en secondaire isolé). Idée centrale empruntée à *Harrier*.
4. **Zéro custody.** Jamais de clé privée, jamais de signature, jamais d'ordre. Observation = données publiques (idée *PolyTerm* « view-only / zero custody »).
5. **Tout est prouvable.** Chaque décision pointe vers ses preuves (feature hash, refs brutes) via un **DecisionLedger append-only** (idée *CloddsBot*).
6. **On ne mélange jamais** PnL LIVE / BACKTEST / REPLAY / TEST_FIXTURE.
7. **Calibration honnête.** On mesure si le bot gagne ou perd ; on ne promet jamais un profit, on ne maquille jamais les chiffres.
8. **Compatible Claude + Codex.** Doc + tests + manifeste d'outils read-only + `llms.txt` pour que les deux agents avancent slice par slice.

---

## 1. Doctrine de sécurité (rappel — la V7 fait foi)

La seule frontière dure : **aucune action réelle externe, aucune clé privée, aucune signature, aucun ordre, aucun dépôt/retrait, aucun wallet connect.**

Tout le reste est autorisé s'il est **local ou read-only** : lecture API publique, WebSocket read-only, scraping public raisonnable, parsing, SQLite local, paper trading, backtest, dashboard local, écriture de fichiers locaux, outils d'agent write-local sur le projet.

Chaque objet simulé porte obligatoirement :

```text
simulation_only = true
not_an_order   = true
external_action = false
venue_mutation  = false
```

> Détails et table de vocabulaire (`BAN_REAL_ACTION` / `READ_ONLY_ALLOWED` / `SIMULATION_ALLOWED` / …) : voir V7 §1–§9.

---

## 2. Honnêteté de domaine : marchés de prédiction vs perpétuels Hyperliquid

**11 des 14 dépôts visent Polymarket/Kalshi (marchés de prédiction binaires YES/NO, prix 0–1, résolution).** Hyperliquid, c'est des **perpétuels à effet de levier** (long/short, mark price, funding, liquidation, pas de « résolution »). Il faut donc trier ce qui transfère.

| Concept du repo source | Transfère vers Hyperliquid ? | Adaptation perp |
|---|---|---|
| Suivi de wallet / copy-trading / smart-money filtering | ✅ Direct | Observer `userFills`/`webData2` d'une adresse, reconstruire positions perp |
| Risk engine (circuit breaker, drawdown, Kelly, kill switch) | ✅ Direct | Identique, + notions perp (levier, marge, liquidation) |
| Microstructure (CVD, VWAP, imbalance, OBI, microprice) | ✅ Direct | Calculé sur `l2Book`/`trades` Hyperliquid |
| Edge net après frais/spread/slippage/latence | ✅ Direct | Barème de frais Hyperliquid + funding |
| Backtest event-driven + execution modeling | ✅ Direct | Replay `fills`/`l2Book`/`candles` Hyperliquid |
| Data-quality gates (stale / depth / spread → NO_TRADE) | ✅ Direct | Seuils sur données Hyperliquid |
| Dashboard + TUI + charts | ✅ Direct | `lightweight-charts` + état paper réel |
| Arbitrage binaire `YES+NO < 1$` | ⚠️ Partiel | Pas d'analogue direct ; proche = **basis / funding-rate arb** cross-exchange (DEFER) |
| Resolution sniper (95¢ → 1$ à la résolution) | ❌ Non | Les perps ne « résolvent » pas ; analogue lointain = capture de funding / mean-reversion |
| Modèles météo (PolyWeather) | ❌ Non (sauf méthode) | On garde **la méthodologie de calibration** (Gaussian/EMOS, shadow mode), pas le domaine |
| Décodage calldata Polygon pour devancer l'API | ⚠️ Concept | Analogue = **WS fills plus rapides que le polling REST** ; pas de mempool perp ici |

**Conclusion :** on garde l'**architecture, le copy-trading, le risque, la microstructure, le backtest, la calibration, le dashboard et l'outillage agent**. On met en DEFER l'arbitrage binaire et le sniping de résolution.

---

## 3. Matrice de fusion — 14 dépôts → idée clé → module HyperSmart

Décision : **KEEP** (intégrer), **ADAPT** (transformer pour perp/paper), **DEFER** (plus tard), **BAN** (jamais — action réelle).

| # | Dépôt | Idées d'or à récupérer | Module cible `hyper_smart_observer/` | Décision |
|---|---|---|---|---|
| 1 | **alsk1992/CloddsBot** | Risk engine unifié (VaR/CVaR, circuit breaker, volatility regime, stress test, Kelly, daily loss, kill switch) ; **Trade/Decision Ledger** append-only + **confidence calibration** (accuracy vs confidence bucket) + hash SHA-256 ; copy-trading & whale tracking ; backtesting ; couche exécution commune (order builder, balance checker, slippage/fee estimator, P&L temps réel) ; persistance SQLite + mémoire sémantique ; **dry-run par défaut** ; MCP server exposant les outils | `risk_engine/`, `ledger/`, `paper_trading/`, `backtesting/`, `dashboard/`, `agent_tools/` | KEEP (ledger, risk, calibration) · BAN (exécution, routing, paiements, token launch, marketplace) |
| 2 | **HarrierOnChain/Prediction-Markets-Toolkits** | **« Un cœur d'exécution + une couche de risque + adapters venue-agnostic »** (ajouter un marché = 1 adapter) ; **Copy Trading multi-wallet** ; **Orderbook Imbalance comme signal** (500 ms) ; **whale signal plus rapide que l'API publique** (→ WS) ; **Circuit Breaker / Depth Guard / Dry-Run / Trade Floor** ; budgets perf (event <1 ms, exec <100 ms, poll ~200 ms/wallet, rate-limit sémaphore) ; **rollout progressif** (trading off → copy 5–10 % → wallet dédié) | `scanner/`, `risk_engine/`, `market_signals/`, `copy_mode/`, `data_sources/` | KEEP (architecture, OBI, gardes) · ADAPT (cœur observation/paper) · BAN (FAK/GTD, market making réel, exec <50 ms) |
| 3 | **MrFadiAi/Polymarket-bot** | **DRY_RUN first-class** ; **Smart-Money filtering** (winrate ≥ 60 %, PnL ≥ 500$, profit factor ≥ 1.5, consistency ≥ 70 %, **anti one-hit-wonder** : max 30 % du PnL d'un seul trade) ; **risk 4 couches** (jour 5 % / mois 15 % / drawdown 25 % / halt total 40 %) ; **sizing dynamique** (−20 %/perte consécutive, +10 %/gain) ; gas/fee accounting ; dashboard mode LIVE/DRY-RUN + risk-status + emergency-stop | `scoring/`, `risk_engine/`, `copy_mode/`, `dashboard/` | KEEP (filtres + halts en mock) · ADAPT (sizing paper) · BAN (private key, panic sell réel, auto-copy réel) |
| 4 | **lihanyu81/polymarket_lp_tool** | **Observateur pur : surveille, ne crée jamais d'ordre** ; whitelist de tokens, skip si position existante ; **modularité nette** (MainLoop/PricePolicy/OrderManager/RewardMonitor/OrderBookFetcher/RiskManager/FillNotif/Telegram/Portfolio/Config) ; **reason codes** explicites ; retries + max API errors ; **fill inference** depuis l'état des ordres ; notifications avec cooldown + dédup empreinte | `realtime_monitor/`, `pipeline/`, `copy_mode/`, `position_lifecycle/` | KEEP (observer pattern, reason codes, fill inference) · ADAPT (mid_stability + cooldown + reconcile) · BAN (OrderManager, cancel/repost) |
| 5 | **yangyuan-zhen/PolyWeather** | **Calibration probabiliste + shadow mode** (legacy Gaussian → EMOS/CRPS, jamais en prod sans éval) ; **model-market difference = edge** ; **SSE temps réel + gap recovery** (replay depuis Redis/SQLite) ; **observabilité** `/healthz` `/status` `/metrics` ; **séparation collecte ↔ entraînement** ; **stale cache bloqué pendant refresh** (ne pas trader sur vieille donnée) ; **evidence chain / invalidation / confirmation rules** ; workflow `.claude` + `.codex` | `scoring/`, `intelligence/`, `dashboard/`, `data_sources/`, `audit/` | KEEP (calibration, shadow, gap recovery, observabilité, stale-block) · ADAPT (DashboardPayload authoritative) · BAN (paiements/onchain checkout) |
| 6 | **Composio-HQ/polymarket-kalshi-arbitrage-bot** | **Timing gates** (n'évaluer qu'après N min) ; schéma de **signal explicite** (`action` + raisons + métriques `spread/edge`) ; endpoints `/health` `/status` `/poll/start|stop` ; polling configurable | `signal_engine/`, `copy_mode/`, `app/` | KEEP (timing gate, schéma signal, status API) · ADAPT (current_signal/no_trade only) · BAN (private key, proxy wallet, trade USD, CLOB) · ⚠️ repo promotionnel « 90 % profitable » → ne garder que la structure |
| 7 | **aarora4/Awesome-Prediction-Market-Tools** | **Taxonomie produit** d'un écosystème complet : AI Agents, Analytics, **Dashboards**, APIs, **Copy Trading**, **Alerting**, **Tracking/leaderboards**, labels (whale/smart/suspicious/fresh) ; existence de **MCP servers** dédiés (PolyClaw, Baozi MCP) | `dashboard/`, `wallet_universe/`, `agent_tools/` | KEEP (checklist de complétude produit) · ADAPT (benchmark features Hyperliquid) · BAN (réplication 1-clic, agents de pari autonomes) |
| 8 | **NYTEMODEONLY/polyterm** | **Zero custody / wallet view-only** ; **copy-trading `follow`** ; **wallet clusters (même entité)** ; smart-money & whale analysis ; **insider scoring, wash-trade detection, risk grading A–F** ; **outillage agent : manifest, JSON Schemas, FastMCP stdio, `doctor`, `llms.txt`/`llms-full.txt`, outils read-only pour Codex** ; **73+ écrans TUI** + onboarding ; **viz terminal** (ASCII charts, sparklines, depth) ; **SQLite stateful** (bookmarks, price alerts, **trade journal**, position tracking, screener presets) ; **Kelly sizing** ; **scheduled scan JSON (agent-safe)** ; 1133 tests | `agent_tools/`, `copy_mode/`, `wallet_universe/`, `scoring/`, `dashboard/`, `storage/` | KEEP (zero custody, follow, clusters, manifest agent, journal, scheduled scan) · ADAPT (manifest read-only Hyperliquid) · BAN (outils write/trade, liens d'exécution) |
| 9 | **txbabaxyz/mlmodelpoly** | **Feature engine microstructure** : CVD, RVOL, impulse, microprice, basis, anchored VWAP, **liquidation tracking** ; **fair value model + edge en bps** ; **Quality Mode OK/DEGRADED/BAD** ; **vetos concrets** : stale > 5 s, min depth, **max spread bps avant veto** ; **caps d'exécution** (slice USD, max slices/fenêtre, cooldown, **edge buffer bps**) ; **event recording → replay** ; REST `/latest/features|bars|edge` + decision_logger + metrics ; **context bootstrap HTF** au démarrage | `market_signals/`, `signal_engine/`, `data_sources/`, `pipeline/` | KEEP (features, quality mode, vetos, edge buffer, recording) · ADAPT (depuis `allMids/l2Book/trades/candles`) · BAN (dépendance hot-path Binance/TAAPI) |
| 10 | **txbabaxyz/polyrec** | **Capture CSV par marché (70+ colonnes)** pour la recherche ; backtests **replicate_balance** (répliquer la courbe d'un wallet !) + **fade_impulse** + visualize ; colonnes clés : `seconds_till_end`, prix oracle/exchange + **`lag`/latence**, returns, ATR/RVOL, **5 niveaux de book**, spread, **imbalance, microprice, depth_slope, eat-flow** | `backtesting/`, `market_signals/`, `storage/` | KEEP (scan_features riches + CSV/JSON export + replicate_balance) · ADAPT (colonnes Hyperliquid) · BAN (logs comme DB primaire) |
| 11 | **evan-kolberg/prediction-market-backtesting** | **Backtest event-driven (NautilusTrader)** + adapters custom ; **execution modeling complet** : fees, **maker rebates**, slippage, **queue position**, **latency**, limits, comportement L2 vendor ; **Account Ledger Replay + interprétation copy-trading** (pourquoi la repro exacte échoue) ; **charting riche** (equity total & par marché, P&L ticks, drawdown, Sharpe, monthly returns, **cumulative Brier advantage**) ; staged loading + caches ; **séparation sandbox/live vs backtest**, **private strategy boundary** ; optimiseurs (random grid, **TPE/Optuna**), joint-portfolio ; `AGENTS.md` | `backtesting/`, `paper_trading/`, `execution/`, `ledger/` | KEEP (parité runtime/backtest, execution modeling, ledger replay, Brier) · ADAPT (modèles Hyperliquid) · BAN (copie de code, contamination de licence, live sandbox exec) |
| 12 | **ent0n29/polybot** | **Séparation ingestion/strategy/analytics/monitoring** ; **mode PAPER par défaut** ; pipeline event (ClickHouse + Redpanda) ; monitoring Grafana/Prometheus/Alertmanager ; **research toolkit : replication & similarity scoring** (à quel point on réplique un wallet cible), calibration, snapshots, execution-quality ; `TARGET_USER`-centric ; vision « fund mirroring » | `pipeline/`, `intelligence/`, `scale/`, `backtesting/` | KEEP (replication scoring, séparation logique, PAPER default) · DEFER (ClickHouse, Kafka, Grafana, microservices) · BAN (executor-service, live, market making) |
| 13 | **Polymarket/agents** | **Modèles de domaine typés (Pydantic)** ; client Gamma propre (métadonnées marché) ; **RAG + vector DB pour news/evidence** ; sourcing multi-source ; CLI comme interface ; tooling LLM (offline) | `models/`, `intelligence/`, `agent_tools/` | KEEP (modèles typés, evidence/RAG offline) · ADAPT (modèles Hyperliquid) · BAN (signing, CLOB, `trade.py` opérationnel) |
| 14 | **tradingview/lightweight-charts** | **Librairie de charts financiers HTML5 performante** : candlesticks, line series, **markers buy/sell**, price lines, plugins | `dashboard/` | KEEP (charts du dashboard : equity paper, fills, lifecycle, drawdown) · ADAPT (jamais de faux mouvement) · ⚠️ attribution TradingView requise (Apache-2.0) |

> **Couverture :** les 14 dépôts sont représentés. Aucune bonne idée n'est laissée de côté ; celles hors-périmètre perp/sécurité sont explicitement classées DEFER ou BAN, pas oubliées.

---

## 4. Architecture cible consolidée

Le flux unique, du marché réel jusqu'au PnL paper, en passant par le filtre NO_TRADE :

```text
                          ┌───────────────────────────────────────────────┐
   Hyperliquid (réel)     │  ADAPTERS read-only (Harrier: 1 adapter/venue) │
   /info REST  ───────────▶  HyperliquidAdapter   (live, read-only)        │
   WebSocket   ───────────▶  MockAdapter          (fixtures/tests)         │
   (public)               │  dYdXAdapter          (secondaire, isolé)      │
                          └───────────────────────┬───────────────────────┘
                                                  │  Common Data Model (CDM)
                                                  ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │ pipeline/  CollectionRun · SourceHealth · cursors · fill_dedupe  │
        │            snapshot_writer · REST reconciler · gap recovery      │  ← PolyWeather, lp_tool
        └───────────────┬─────────────────────────────────────────────────┘
                        ▼
   market_signals/  mid_stability · orderbook features (OBI, microprice,    ← mlmodelpoly, polyrec, Harrier
                    depth_slope) · volatility · liquidity_score · edge       
                        │
   wallet_universe/ + scoring/   WalletScore · CopyabilityScore · labels     ← MrFadi, polyterm, polybot
   wallet_discovery/             leaderboard · clusters (même entité)        
                        │
   position_lifecycle/  fills → OPEN / ADD / REDUCE / CLOSE / FLIP           ← backtesting (ledger replay)
                        │        (deny si ambigu → NO_TRADE)
                        ▼
   copy_mode/  delta_detector → signal_candidate                            ← Harrier, Composio (timing gate)
                        │
   risk_engine/  DENY-BY-DEFAULT gates · circuit breaker · cooldown ·        ← MrFadi (4 halts), CloddsBot
                 mock halts (5/15/25/40) · Kelly sizing                      
                        │           │
                 (rejet)▼           ▼(accepté)
   no_trade/  NoTradeDecision   PaperIntent ─▶ paper_trading/ (PaperEngine)  ← MrFadi DRY_RUN, polybot PAPER
   + reason_codes                  │            fills + frais + spread +
                                   │            slippage + latence + copy_deg
                                   ▼
   execution/ (paper only)  exit_engine: follow reduce/close, stops,        ← Harrier, backtesting
                            trailing, MAE/MFE, notional cap                  
                                   ▼
   ledger/  DecisionLedger append-only + evidence_chain + SHA-256           ← CloddsBot, PolyWeather
                                   ▼
   ┌──────────────────────┬──────────────────────┬───────────────────────┐
   │ dashboard/           │ backtesting/         │ agent_tools/          │
   │ lightweight-charts   │ replay fills/books   │ manifest read-only    │
   │ equity/fills/risk    │ parité runtime/paper │ llms.txt · FastMCP    │
   │ (TradingView)        │ Brier · TPE/Optuna   │ (PolyTerm, agents)    │
   └──────────────────────┴──────────────────────┴───────────────────────┘
                                   ▼
        storage/  SQLite local — séparation stricte des espaces de PnL :
        LIVE · BACKTEST · REPLAY · TEST_FIXTURE  (jamais mélangés)
```

**Règles d'architecture (non négociables) :**

- **Un seul `risk_engine`** partagé par runtime, paper et backtest (parité — *backtesting* repo).
- **Un seul `paper_trading` (PaperEngine existant)** — ne jamais créer un moteur PnL parallèle (V7 §0A).
- **Adapters read-only uniquement** : `HyperliquidAdapter` n'importe jamais le SDK `Exchange`/order/signing.
- **dYdX reste isolé** (`hyper_smart_observer/dydx_v4/`), non importé par défaut au runtime Hyperliquid, conservé comme benchmark/mockable (couche d'abstraction commune = bénéfice gratuit).
- **`mode` est un champ porté partout** : `LIVE | BACKTEST | REPLAY | TEST_FIXTURE`. Le PnL est agrégé **par mode**.

---

## 5. Le contrat de données Hyperliquid (read-only) → Common Data Model

Tout ce qui suit est **lecture publique**. Aucune adresse n'a besoin de clé pour être observée.

### 5.1 Sources REST `/info` (POST `{"type": ...}`)

| `type` | Donne | Usage HyperSmart |
|---|---|---|
| `allMids` | mids de tous les coins | prix de mark-to-market paper ; `mid_source` + `data_quality` obligatoires |
| `l2Book` | carnet niveau 2 (profondeur limitée) | spread, liquidity_score, microprice, depth imbalance (OBI) |
| `clearinghouseState` (user) | positions + marge d'une adresse | reconstruction position leader |
| `userFills` / `userFillsByTime` | fills d'une adresse | **cœur copy-observer** : lifecycle OPEN/ADD/REDUCE/CLOSE |
| `candleSnapshot` | bougies | volatilité (realized_vol, ATR, range), bootstrap HTF |
| `meta` / `metaAndAssetCtxs` | univers + funding/mark/oracle | mapping marché, funding, mark vs oracle |
| `openOrders` / `frontendOpenOrders` | ordres ouverts | **contexte uniquement**, jamais preuve d'intention suffisante |

**Contraintes à coder/tester** (déjà listées V6 §3, à respecter) : pagination time-range par blocs de 500, `next startTime = dernier ts + garde anti-boucle` ; fenêtres bornées avec metadata `window_complete / truncated / oldest_available_ts / stopped_reason` ; `allMids` peut retomber sur le last trade si book vide → `mid_source` + `data_quality` ; rate limits (budget REST pondéré).

### 5.2 Sources WebSocket (`wss://api.hyperliquid.xyz/ws`, read-only)

`allMids`, `trades`, `l2Book`, `bbo`, `candle`, et **user-specific** : `userFills`, `userEvents`, `webData2`, `orderUpdates`.

**Robustesse obligatoire** (idées *lp_tool* + *PolyWeather*) : heartbeat/ping, reconnect + backoff exponentiel, ack d'abonnement, gestion `isSnapshot:true` puis updates, **dédup snapshot/update**, **gap recovery** (rejouer le trou), fallback REST polling, durée bornée, `source_health` par flux. **Limites :** max 10 connexions, 1000 subs, **10 wallets user-specific** → architecture obligatoire : *REST broad scan/backfill → WalletScore/shortlist → WS sur ≤10 wallets → REST reconciliation*.

### 5.3 Common Data Model (chaque objet porte ces champs)

```text
venue · source_endpoint|source_channel · source_ts · local_received_ts · latency_ms ·
raw_ref|raw_hash · data_quality · is_stale · schema_version · adapter_version · mode
```

Modèles (créer/renforcer dans `models/`) : `NormalizedFill`, `NormalizedPosition`, `NormalizedOpenOrder`, `MarketMid`, `OrderBookSnapshot`, `MarketSignalFeatures`, `WalletSnapshot`, `CollectionRun`, `SourceHealth`, `LeaderDelta`, `PositionEpisode`, `SignalCandidate`, `NoTradeDecision`, `RiskDecision`, `PaperIntent`, `PaperTrade`, `DecisionLedgerEntry`, `DashboardEvent`, `BacktestEvent`.

---

## 6. Les 4 formules fusionnées (le cerveau du bot)

### 6.1 WalletScore + CopyabilityScore (fusion MrFadi + PolyTerm + polybot)

On ne copie **que** des wallets qui ont prouvé un edge **répétable et copiable**. Filtres durs (sinon le wallet n'entre pas dans la shortlist) :

```text
HARD FILTERS (deny-by-default)
- trade_count            >= MIN_TRADES (ex. 30)            # assez d'échantillon
- winrate                >= 0.55–0.60
- profit_factor          >= 1.5                            # somme gains / somme pertes
- consistency_score      >= 0.70                           # perf récente cohérente
- one_big_win_ratio      <= 0.30                           # anti one-hit-wonder (MrFadi)
- pnl_concentration      <= seuil                          # PnL pas dû à 1 coin/1 trade
- recent_activity        within N days                     # pas un wallet mort
- max_drawdown_leader    <= seuil
```

Score continu (0–1) pour le ranking de la shortlist :

```text
WalletScore = w1*winrate_norm + w2*profit_factor_norm + w3*consistency
            + w4*sharpe_like   + w5*recency           − w6*concentration_penalty
            − w7*overtrading_penalty
```

**CopyabilityScore** = à quel point un *copieur en retard* capterait l'edge (clé pour les perps rapides) :

```text
CopyabilityScore = f( holding_time_median,        # plus c'est court, moins c'est copiable
                      avg_slippage_if_followed,
                      market_liquidity,
                      copy_degradation_bps,        # cf. 6.4
                      edge_remaining_after_lag )
```

Labels (PolyTerm) : `smart` / `whale` / `suspicious` / `fresh` + `INSUFFICIENT_DATA` si échantillon trop faible. Clusters : regrouper les adresses d'une **même entité** avant de scorer (éviter de compter 1 trader comme 5).

### 6.2 Edge net après coûts (fusion mlmodelpoly + backtesting + Harrier)

Un signal n'est jamais pris si l'edge net n'est pas franchement positif :

```text
edge_gross_bps      = (fair_value − entry_price) en bps         # fair model (mlmodelpoly)
edge_net_bps        = edge_gross_bps
                      − fees_bps                                  # barème Hyperliquid (maker/taker)
                      − half_spread_bps                           # depuis l2Book
                      − slippage_bps(taille, profondeur)          # depth-aware
                      − latency_cost_bps                          # retard signal→action (lag, polyrec)
                      − copy_degradation_bps                      # cf. 6.4
                      ± funding_bps                               # spécifique perp

PRENDRE le signal SEULEMENT si :  edge_net_bps >= EDGE_BUFFER_BPS  (ex. 35 bps, cf. launcher)
```

> Garde anti-illusion : `EDGE_BUFFER_BPS` (marge de sécurité, mlmodelpoly) impose un edge *au-delà* du seuil de rentabilité, pas juste positif.

### 6.3 NO_TRADE gates — deny-by-default (fusion mlmodelpoly + lp_tool + PolyWeather + Composio)

Le moteur **rejette par défaut**. Un signal doit franchir **toutes** les portes, sinon `NoTradeDecision(reason_code=...)` :

```text
1. STALE_SIGNAL        signal_age_ms  > MAX_SIGNAL_AGE_MS (ex. 6000)
2. STALE_MARKET        mid/book age   > stale_threshold ; data_quality != OK
3. LOW_LIQUIDITY       liquidity_score < MIN_LIQUIDITY_SCORE (ex. 0.5)
4. WIDE_SPREAD         spread_bps      > MAX_SPREAD_BPS
5. MISSING_BOOK        l2Book absent / dégradé
6. LOW_EDGE            edge_net_bps    < EDGE_BUFFER_BPS
7. AMBIGUOUS_LIFECYCLE delta UNKNOWN / close orphelin / flip ambigu
8. BAD_MARKET_MAP      coin mal mappé / inconnu
9. HIGH_COPY_DEGRAD    copy_degradation_bps > MAX_COPY_DEGRADATION_BPS (ex. 12)
10. RISK_BLOCK         circuit breaker / cooldown / halt actif / notional cap
11. TIMING_GATE        hors fenêtre autorisée (Composio)
12. INSUFFICIENT_DATA  wallet/feature sous le minimum d'échantillon
```

Chaque rejet est **loggé avec son reason_code** et visible au dashboard (distribution des raisons = métrique de santé du filtre).

### 6.4 Copy-degradation & Replication score (fusion polybot + backtesting account-ledger-replay)

Mesurer **honnêtement** l'écart entre le leader et le copieur paper :

```text
copy_degradation_bps = (prix_entrée_copieur − prix_entrée_leader) en bps
                       + impact lié à la latence WS/REST
                       + impact lié à la taille (profondeur consommée)

ReplicationScore = similarité( courbe equity leader , courbe equity copieur paper )
                   sur la même fenêtre  →  ∈ [0,1]
```

> Leçon du repo *backtesting* (account-ledger-replay) : **la reproduction exacte échoue toujours** (latence, fills partiels, file d'attente). On mesure l'écart, on ne le cache pas. `ReplicationScore` devient un KPI du dashboard et un critère de `CopyabilityScore`.

---

## 7. Feuille de route exécutable — slices verticales (S0 → S10)

**Comment un agent (Claude ou Codex) exécute ce plan :**

1. Faire **une slice à la fois**, dans l'ordre (chaque slice est un *vertical slice* livrable et testable).
2. Pour chaque slice : `git status` → coder → tests → `--safety-check` / `--audit-safety` → rapport FR.
3. **Definition of Done par slice** = tous les *tests d'acceptation* listés passent **et** la garde sécurité est vérifiée.
4. Ne jamais avancer à la slice suivante si la précédente n'est pas verte.

Légende effort : 🟢 court · 🟡 moyen · 🔴 gros. Chaque slice cite ses **repos sources** et reste **paper/read-only**.

---

### S0 — Préflight & garde-fous (🟢)

- **But.** Garantir l'état sain avant tout : Hyperliquid-only, simulation préservée, dYdX isolé.
- **Repos.** —
- **Fichiers.** `LANCER_HYPERSMART.cmd`, `tools/start_hypersmart_simulation.ps1`, `hyper_smart_observer/audit/`, `hyper_smart_observer/app/`.
- **Livrables.** `--safety-check` + `--audit-safety` verts ; vérifier les gardes du launcher (`HL_ENV=paper`, `HL_ENABLE_*_EXECUTION=0`, `HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW`, `MAX_SIGNAL_AGE_MS=6000`, `MIN_EDGE_BPS=35`, `MIN_LIQUIDITY_SCORE=0.5`, `MAX_COPY_DEGRADATION_BPS=12`).
- **Tests d'acceptation.** `test_launcher_guards_match_runtime.py`, `test_no_dydx_default_runtime_import.py`, `test_no_polymarket_runtime_or_clob.py`.
- **Commandes.** `git status --short` · `python -m hl_observer safety-audit` · `python -m hl_observer audit-safety`.
- **Garde sécurité.** Aucune mutation externe possible ; clés absentes.

---

### S1 — Common Data Model + Adapter read-only Hyperliquid (🟡)

- **But.** Figer le CDM (§5.3) et le `HyperliquidAdapter` read-only derrière une `BaseAdapter` (un adapter par venue).
- **Repos.** Harrier (adapter venue-agnostic), Polymarket/agents (modèles Pydantic typés), PolyWeather (data_quality/source_health).
- **Fichiers.** `hyper_smart_observer/models/`, `hyper_smart_observer/data_sources/`, `hyper_smart_observer/hyperliquid_client/`, (réutiliser `dydx_v4/normalizer.py`, `dydx_v4/models.py` comme référence d'abstraction).
- **Livrables.** `BaseAdapter` + `HyperliquidAdapter` (info REST + WS), `MockAdapter` (fixtures), chaque objet portant les champs CDM (`source_ts`, `latency_ms`, `data_quality`, `is_stale`, `schema_version`, `mode`).
- **Tests d'acceptation.** `test_hyperliquid_adapter_never_imports_exchange.py`, `test_cdm_fields_present_all_models.py`, `test_mock_adapter_fixtures_load.py`, `test_allmids_mid_source_and_quality.py`.
- **Garde sécurité.** `HyperliquidAdapter` n'importe jamais `Exchange`/signing ; tout est POST `/info` + WS read-only.

---

### S2 — Pipeline d'ingestion : scan REST → shortlist → WS ≤10 → reconciliation (🔴)

- **But.** L'architecture obligatoire de débit Hyperliquid avec dédup, pagination, gap recovery, source_health.
- **Repos.** Harrier (rate-limit sémaphore, whale signal via WS), lp_tool (WS-first + REST reconciliation, dédup, retries), PolyWeather (gap recovery, observabilité).
- **Fichiers.** `hyper_smart_observer/pipeline/`, `hyper_smart_observer/scanner/`, `hyper_smart_observer/realtime_monitor/`, `hyper_smart_observer/wallet_discovery/`.
- **Livrables.** `CollectionRun`, `SourceHealth`, curseurs de pagination (blocs 500 + anti-boucle), `fill_dedupe`, snapshot writer SQLite, reconciler REST ; WS heartbeat/reconnect/backoff/ack/`isSnapshot` dédup ; **cap strict 10 wallets WS**.
- **Tests d'acceptation.** `test_pagination_500_blocks_no_loop.py`, `test_ws_runtime_heartbeat_reconnect_dedupe.py`, `test_gap_recovery_replays_missing.py`, `test_fill_dedupe_idempotent.py`, `test_ws_user_cap_max_10.py`, `test_source_health_degraded_marks_stale.py`.
- **Garde sécurité.** WS et REST read-only ; durées bornées ; pas de boucle infinie.

---

### S3 — Market signal features + edge net (🟡)

- **But.** Calculer les features microstructure et l'**edge net après coûts** (§6.2) depuis données Hyperliquid.
- **Repos.** mlmodelpoly (CVD, RVOL, microprice, anchored VWAP, fair model, edge bps, quality mode, vetos), polyrec (scan_features riches, depth_slope, imbalance, lag), Harrier (OBI).
- **Fichiers.** `hyper_smart_observer/market_signals/`, `dydx_v4/edge_calculator.py` (référence), `hyper_smart_observer/signal_engine/`.
- **Livrables.** `MarketSignalFeatures` (mid_stability, spread_bps, depth_imbalance/OBI, microprice, depth_slope, volatility_context, liquidity_score) ; `EdgeCalculator.edge_net_bps(...)` avec fees+spread+slippage+latency+copy_deg+funding ; `feature_hash` ; export CSV/JSON (scan_features).
- **Tests d'acceptation.** `test_edge_net_subtracts_all_costs.py`, `test_volatility_context_live_from_candle_snapshot.py`, `test_features_degraded_when_book_missing.py`, `test_obi_microprice_from_l2book.py`, `test_scan_features_export_columns.py`.
- **Garde sécurité.** Si donnée absente → `None`/dégradé, **jamais inventé**.

---

### S4 — Wallet intelligence : WalletScore + CopyabilityScore + clusters + leaderboard (🔴)

- **But.** Trouver et classer les wallets vraiment copiables (§6.1).
- **Repos.** MrFadi (smart-money filters, anti one-hit-wonder), PolyTerm (clusters, labels, follow), polybot (replication/similarity scoring), CloddsBot (whale tracking).
- **Fichiers.** `hyper_smart_observer/scoring/`, `hyper_smart_observer/wallet_universe/`, `hyper_smart_observer/wallet_discovery/`, `dydx_v4/leaderboard.py` + `dydx_v4/leader_quality.py` (référence).
- **Livrables.** Filtres durs + `WalletScore` continu + `CopyabilityScore` + labels (`smart/whale/suspicious/fresh/INSUFFICIENT_DATA`) + détection de **clusters même-entité** + import leaderboard public.
- **Tests d'acceptation.** `test_wallet_hard_filters_reject_one_hit_wonder.py`, `test_copyability_penalizes_short_holding.py`, `test_clusters_merge_same_entity.py`, `test_insufficient_data_label.py`, `test_leaderboard_import_readonly.py`.
- **Garde sécurité.** Lecture publique d'adresses uniquement ; aucune donnée privée.

---

### S5 — Position lifecycle : OPEN / ADD / REDUCE / CLOSE / FLIP (🔴)

- **But.** Reconstruire les épisodes de position du leader à partir des `userFills` (champs `dir`, `startPosition`, `closedPnl`, `fee`, `hash`, `oid`, `tid`, `crossed`, `liquidation`).
- **Repos.** backtesting (account-ledger-replay, interprétation copy-trading), lp_tool (fill inference).
- **Fichiers.** `hyper_smart_observer/position_lifecycle/`, `dydx_v4/lifecycle.py` (référence).
- **Livrables.** `PositionEpisode` par account/subaccount/market/side ; gestion fills partiels, closes partiels, entry/exit moyens, holding time, realized PnL leader, **lifecycle_confidence**.
- **Tests d'acceptation.** `test_position_lifecycle_hyperliquid_fields.py`, `test_position_lifecycle_ambiguous_flip_no_trade.py`, `test_orphan_close_refused.py`, `test_partial_fills_average_entry.py`.
- **Garde sécurité.** Lifecycle ambigu / close orphelin / delta UNKNOWN → `NoTradeDecision`, jamais `PaperIntent`.

---

### S6 — Copy signal + RiskEngine deny-by-default + NO_TRADE (🟡)

- **But.** Transformer un delta leader en `SignalCandidate`, le passer par toutes les portes NO_TRADE (§6.3) et le RiskEngine, puis émettre `PaperIntent` **ou** `NoTradeDecision`.
- **Repos.** Harrier (circuit breaker, depth guard, cooldown), MrFadi (halts 5/15/25/40, sizing dynamique), Composio (timing gate), CloddsBot (kill switch, Kelly).
- **Fichiers.** `hyper_smart_observer/copy_mode/`, `hyper_smart_observer/risk_engine/`, `hyper_smart_observer/signal_engine/`, `dydx_v4/no_trade.py` + `dydx_v4/risk_policy.py` (référence).
- **Livrables.** `delta_detector` → `SignalCandidate` ; `RiskEngine` (gates + circuit breaker + cooldown wallet/symbol/action + mock halts + notional cap + Kelly sizing paper) ; `NoTradeDecision(reason_code)` + distribution des raisons.
- **Tests d'acceptation.** `test_no_trade_stale_signal.py`, `test_no_trade_low_edge.py`, `test_no_trade_low_liquidity.py`, `test_no_trade_wide_spread.py`, `test_risk_halt_5_15_25_40_mock.py`, `test_cooldown_blocks_duplicate.py`, `test_circuit_breaker_trips_and_cools_down.py`.
- **Garde sécurité.** `PaperIntent` n'existe **qu'après** RiskEngine ; deny-by-default.

---

### S7 — PaperEngine : intent → fill simulé → PnL → equity (🔴)

- **But.** Brancher le pipeline sur le **PaperEngine existant** (ne pas en créer un second — V7 §0A) avec coûts réalistes.
- **Repos.** MrFadi (DRY_RUN), polybot (PAPER default), backtesting (execution modeling : fees, maker rebate, slippage, queue, latency), CloddsBot (P&L temps réel).
- **Fichiers.** `hyper_smart_observer/paper_trading/`, `hyper_smart_observer/execution/`, `dydx_v4/paper.py` + `dydx_v4/fill_simulator.py` + `dydx_v4/paper_fill.py` (référence).
- **Livrables.** `PaperIntent → PaperTrade` (marqué `not_an_order`), fill simulé depth-aware, frais/spread/slippage/latence/copy_degradation appliqués, PnL réalisé + latent (mark-to-market sur `allMids`/WS), equity curve, drawdown, **mock USDC** ; PnL **séparé par mode** (`LIVE/BACKTEST/REPLAY/TEST_FIXTURE`).
- **Tests d'acceptation.** `test_paper_engine_existing_simulation_not_replaced.py`, `test_paper_trade_is_marked_not_order.py`, `test_pnl_long_and_short_correct.py`, `test_fees_not_double_counted.py`, `test_pnl_modes_never_mixed.py`, `test_unrealized_pnl_marked_to_market.py`.
- **Garde sécurité.** `PaperTrade` ne touche jamais d'API externe ; close paper = local only.

---

### S8 — Exit engine paper (follow reduce/close, stops, trailing, MAE/MFE) (🟡)

- **But.** Simuler la sortie : suivre les reduce/close du leader + stops locaux.
- **Repos.** Harrier (TP/SL en idée → paper), backtesting (MAE/MFE), MrFadi (stop-loss/take-profit/max hold).
- **Fichiers.** `hyper_smart_observer/execution/` (exit_engine), `dydx_v4/adaptive_exits.py` (référence).
- **Livrables.** follow leader reduce/close, partial close, time stop, trailing stop, max MAE/MFE, max holding time, max open positions, blocked assets, notional cap, duplicate guard ; **si pas de position paper correspondante → NoTrade**.
- **Tests d'acceptation.** `test_exit_engine_follow_reduce_close.py`, `test_exit_engine_no_matching_position_no_trade.py`, `test_trailing_and_time_stop.py`, `test_mae_mfe_tracked.py`.
- **Garde sécurité.** Aucun ordre réel ; aucune référence `/exchange`.

---

### S9 — DecisionLedger + EvidenceChain + calibration (🟡)

- **But.** Rendre chaque décision **auditable et reproductible**.
- **Repos.** CloddsBot (ledger + confidence calibration + SHA-256), PolyWeather (evidence chain / invalidation / confirmation), backtesting (Brier), Polymarket/agents (evidence/RAG offline).
- **Fichiers.** `hyper_smart_observer/ledger/`, `hyper_smart_observer/intelligence/`, `dydx_v4/decision_log.py` (référence).
- **Livrables.** `DecisionLedgerEntry` append-only reliant `decision_id → feature_hash`, refs brutes (allMids/l2Book/candles/fills), `signal_candidate_id/no_trade_id/paper_intent_id/paper_trade_id`, reason_codes, hash SHA-256 reproductible ; **confidence calibration** (accuracy par bucket de confiance) ; **cumulative Brier advantage**.
- **Tests d'acceptation.** `test_decision_ledger_evidence_chain_feature_hash.py`, `test_decision_hash_reproducible.py`, `test_no_decision_without_evidence.py`, `test_confidence_calibration_buckets.py`.
- **Garde sécurité.** Aucune ref factice ; ledger en SQLite local.

---

### S10 — Backtest/Replay (parité runtime) + Dashboard + Agent tools (🔴)

- **But.** Boucler : mesurer la performance honnêtement + la montrer + l'exposer aux agents.
- **Repos.** backtesting (replay fills/books/deltas, parité, TPE/Optuna, charting), polyrec (replicate_balance), lightweight-charts (dashboard), PolyTerm (manifest agent, llms.txt, scheduled scan, trade journal, screener), CloddsBot (reports/diagnostics), Awesome-list (checklist de complétude).
- **Fichiers.** `hyper_smart_observer/backtesting/`, `hyper_smart_observer/dashboard/`, `hyper_smart_observer/agent_tools/`, `dydx_v4/backtest.py` (référence), `docs/llms.txt`.
- **Livrables.**
  - **Backtest/Replay** : rejoue fills + deltas + book snapshots avec délais WS/60 s/5 min, missed fills, fees/spread/slippage/latence ; **mêmes modèles que runtime/paper** (parité) ; equity/drawdown, Sharpe/Sortino/Calmar, monthly returns, distribution NO_TRADE, calibration ; optimiseurs random-grid + TPE ; **PnL jamais mélangé entre LIVE/BACKTEST/REPLAY/TEST_FIXTURE**.
  - **Dashboard read-only** (`lightweight-charts`) : statut scanner, source_health, shortlist + scores, deltas leader, signal candidates, **no_trade report + distribution reason_codes**, edge_remaining, copy_degradation, lifecycle, paper portfolio (positions du simulateur uniquement), PnL réalisé/latent, equity/drawdown, risk events, ReplicationScore, backtests ; **charts réels uniquement, aucun faux mouvement** ; trade journal + screener presets (PolyTerm).
  - **Agent tools** read-only : manifest + JSON Schemas + `llms.txt` ; outils `status.read`, `wallet.leaderboard`, `decision_ledger.search`, `dashboard.export`, `source_health.read`, `archive.status/search` ; outils local-write de simulation (`simulation.start/stop`, `paper_position.close_local`, `backtest.run`, `research.rescan_sources`, `watchlist.import_local`) ; **scheduled scan JSON agent-safe**.
- **Tests d'acceptation.** `test_backtest_replay_from_fills_deltas_books.py`, `test_backtest_runtime_paper_parity_reason_codes.py`, `test_pnl_modes_never_mixed.py`, `test_dashboard_live_no_fake_placeholders.py`, `test_agent_safe_manifest_readonly_only.py`, `test_local_write_tools_do_not_call_external_trade_api.py`, `test_scheduled_scan_outputs_json.py`.
- **Garde sécurité.** Outils read-only purs côté produit ; les outils write sont **local-only** ; dashboard sans faux PnL.

---

### Dépendances entre slices

```text
S0 ─▶ S1 ─▶ S2 ─▶ S3 ─┐
                      ├─▶ S6 ─▶ S7 ─▶ S8 ─▶ S9 ─▶ S10
        S4 ───────────┤
        S5 ───────────┘
```

> **Chemin le plus court vers « est-ce que le bot gagne ou perd ? »** : S0 → S1 → S2 → **S5 → S6 → S7 → S8** → S10 (backtest). Le scoring fin (S4) et l'edge avancé (S3) peuvent être enrichis en parallèle, mais S6 a besoin d'un edge minimal et d'un lifecycle correct.

---

## 8. Mode opératoire Claude + Codex (prompts prêts à coller)

**Répartition recommandée des rôles :**

- **Claude (toi) :** conception, lecture/recherche GitHub & docs, revue de cohérence, audits de sécurité, rédaction des specs de slice, revue de PR/diffs, vérification finale.
- **Codex :** exécution intensive d'une slice (code + tests), boucle rouge→vert, refactors mécaniques, génération de fixtures.

**Boucle par slice (identique pour les deux agents) :**

```text
1. git status --short  &&  git diff --stat
2. Lire docs/HYPERSMART_FUSION_ROADMAP_V8.md (la slice en cours) + V7 (doctrine)
3. Coder le vertical slice (fichiers listés)  — NE RIEN SUPPRIMER
4. Écrire/мettre à jour les tests d'acceptation de la slice
5. python -m pytest -q <tests de la slice>
6. python -m hl_observer safety-audit  &&  python -m hl_observer audit-safety
7. Rapport FR (format §11)  →  passer à la slice suivante seulement si tout est vert
```

**Prompt court à donner à Codex (objectif) :**

```text
Lis docs/HYPERSMART_FUSION_ROADMAP_V8.md et docs/CODEX_HYPERSMART_MASTER_PLAN_V7_ACTION_BOUNDARY.md.
Doctrine V7 : seule interdiction dure = action réelle externe ; tout le reste (read-only, simulation,
backtest, write-local) est autorisé. Runtime Hyperliquid-only, simulation paper, /info + WebSocket
read-only. Ne supprime rien ; dYdX reste isolé ; pas de Polymarket runtime ; pas de fausse donnée.
Travaille local only dans C:\Users\flo\Desktop\Projet invest.
Exécute la prochaine slice non terminée (S0→S10) : code réel + tests d'acceptation listés +
safety-check + audit-safety, puis rapport FR (fichiers, tests, commandes, résultats, limites,
prochaine étape, confirmation sécurité). Avance une seule slice, ne saute pas les tests.
```

**Prompt de revue (à me redonner, Claude) :**

```text
Relis le diff de la slice <S?> contre docs/HYPERSMART_FUSION_ROADMAP_V8.md :
vérifie parité runtime/paper/backtest, gates NO_TRADE, séparation des modes PnL, zéro action externe,
zéro clé, zéro fausse donnée. Liste les écarts et les tests manquants.
```

---

## 9. Suite de tests obligatoires (consolidée — checklist projet)

Sécurité & doctrine : `test_no_real_order_possible.py`, `test_config_safe_by_default.py`, `test_agent_tools_cannot_access_private_keys.py`, `test_audit_flags_external_order_post.py`, `test_no_polymarket_runtime_or_clob.py`, `test_no_dydx_default_runtime_import.py`, `test_launcher_guards_match_runtime.py`.

Données & robustesse : `test_rest_mocked.py`, `test_websocket_mocked.py`, `test_ws_runtime_heartbeat_reconnect_dedupe.py`, `test_gap_recovery_replays_missing.py`, `test_fill_dedupe_idempotent.py`, `test_pagination_500_blocks_no_loop.py`, `test_source_health_degraded_marks_stale.py`.

Logique cœur : `test_position_lifecycle_open_add_reduce_close.py`, `test_orphan_close_refused.py`, `test_no_trade_stale_signal.py`, `test_no_trade_low_edge.py`, `test_no_trade_low_liquidity.py`, `test_no_trade_wide_spread.py`, `test_edge_net_subtracts_all_costs.py`.

PnL & parité : `test_pnl_long_and_short_correct.py`, `test_fees_not_double_counted.py`, `test_pnl_modes_never_mixed.py` (LIVE/BACKTEST/REPLAY/TEST_FIXTURE), `test_backtest_runtime_paper_parity_reason_codes.py`, `test_paper_engine_existing_simulation_not_replaced.py`.

Produit : `test_dashboard_live_no_fake_placeholders.py` (read-only, charts réels), `test_agent_safe_manifest_readonly_only.py`, `test_wallet_hard_filters_reject_one_hit_wonder.py`.

> Cible long terme inspirée de PolyTerm (1133 tests) : couvrir API, core, lifecycle, risk, paper, backtest, dashboard, agent, DB.

---

## 10. Limites & risques honnêtes (à garder en tête)

1. **Aucune promesse de PnL.** Le logiciel *mesure* la simulation ; il optimise la probabilité d'un PnL paper réaliste positif, sans jamais le garantir ni maquiller les chiffres.
2. **Domaine.** 11/14 dépôts sont des marchés de prédiction (binaire/résolution) ; l'arbitrage `YES+NO<1$` et le resolution sniper **ne transfèrent pas** aux perps (classés DEFER/BAN, cf. §2).
3. **Copy-degradation réelle.** Sur des perps rapides, un copieur en retard capte une fraction de l'edge ; `copy_degradation_bps` et `ReplicationScore` rendent ce coût visible — un wallet « génial » mais non copiable doit être recalé par `CopyabilityScore`.
4. **Limites API Hyperliquid.** 10 wallets WS max, profondeur `l2Book` limitée, fenêtres `userFills` bornées : d'où l'architecture *scan REST → shortlist → WS ≤10 → reconciliation*. Le `l2Book` sert à estimer spread/liquidité, **pas** à promettre une exécution profonde.
5. **Données manquantes/vieilles.** En cas de doute (stale, dégradé, incomplet) → **NO_TRADE**, jamais une position de secours.
6. **Passage au réel (plus tard).** Tout est conçu pour qu'« activer le réel » = brancher un `ExecutionAdapter` derrière la même `BaseAdapter` et le même RiskEngine. Ce franchissement reste **hors périmètre** tant que la doctrine simulation-only est active et exige une revue manuelle explicite.
7. **Licences.** Ne pas copier de code ; extraire des idées. `lightweight-charts` (Apache-2.0) exige l'attribution TradingView ; `prediction-market-backtesting` mélange GPL/LGPL/MIT → s'inspirer sans copier.

---

## 11. Definition of Done + phrase de sécurité

**Une slice est terminée seulement si :**

- aucune suppression de la simulation/historique/tests/launcher existants ;
- runtime Hyperliquid-only préservé, dYdX isolé, aucun runtime Polymarket ;
- code réel (pas seulement des docs) + tests d'acceptation de la slice **verts** ;
- `safety-check` / `audit-safety` passent (ou échecs documentés honnêtement) ;
- dashboard sans fausse donnée ; PaperEngine existant conservé ;
- PnL séparé par mode (LIVE/BACKTEST/REPLAY/TEST_FIXTURE) ;
- rapport FR : fichiers modifiés, bugs trouvés, corrections, tests lancés, limites, prochaines étapes, **confirmation sécurité**.

**Phrase de sécurité finale obligatoire à chaque rapport :**

> Runtime Hyperliquid-only, simulation paper uniquement, PaperEngine préservé, aucun `/exchange`, **0 ordre réel, 0 argent réel, 0 clé privée, 0 signature, 0 dépôt/retrait**, aucune fausse donnée, dYdX isolé.

---

### Annexe — table « repo → slice » (vérification : tout est utilisé)

| Repo | Slices où l'idée est exécutée |
|---|---|
| CloddsBot | S6 (risk/Kelly), S7 (P&L), S9 (ledger+calibration), S10 (reports/dashboard) |
| Harrier Toolkits | S1 (adapter), S2 (WS rapide, rate-limit), S3 (OBI), S6 (circuit breaker/depth guard) |
| MrFadiAi/Polymarket-bot | S4 (smart-money filters, anti one-hit), S6 (halts 5/15/25/40, sizing), S7 (DRY_RUN) |
| polymarket_lp_tool | S2 (WS-first + reconcile + dédup), S5 (fill inference), S6 (reason codes, cooldown) |
| PolyWeather | S2 (gap recovery, observabilité), S3 (stale-block), S9 (evidence chain, shadow/calibration) |
| Composio arb bot | S6 (timing gate, schéma signal), S10 (status API) |
| Awesome-Prediction-Market-Tools | S4/S10 (checklist de complétude : analytics, alerting, tracking, copy) |
| PolyTerm | S4 (clusters/labels/follow), S7 (Kelly), S10 (manifest agent, llms.txt, journal, screener, scheduled scan) |
| mlmodelpoly | S3 (features microstructure, fair model, edge bps, quality mode, vetos, recording) |
| polyrec | S3 (scan_features riches), S10 (replicate_balance, CSV export) |
| prediction-market-backtesting | S7 (execution modeling), S9 (Brier), S10 (replay parité, TPE/Optuna, charting) |
| polybot | S4 (replication scoring), S10 (séparation ingestion/analytics — DEFER scale) |
| Polymarket/agents | S1 (modèles typés), S9 (evidence/RAG offline) |
| lightweight-charts | S10 (charts dashboard : equity, fills, drawdown) |

*Fin du document — feuille de route fusionnée V8. Aucune bonne idée des 14 dépôts n'est laissée de côté ; les idées hors-périmètre sont explicitement classées DEFER/BAN, traçables ci-dessus.*

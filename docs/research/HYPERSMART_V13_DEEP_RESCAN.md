# HyperSmart V13 — Deep Re-scan des 14 GitHub (READMEs réels)

> Re-lecture des **vrais READMEs** (pas mes résumés). Contrainte ABSOLUE : **méthodes
> GRATUITES uniquement** — aucune API payante, aucune donnée payante, aucun secret
> (TAAPI.io, OpenAI cloud…) dans le hot-path. Paper-only / read-only / 0 ordre réel.
> Repos lus en direct : 01,02,03,04,06,09,10,11,12,13 (10/14). Les 4 restants
> (05 PolyWeather, 07 Awesome, 08 PolyTerm, 14 lightweight-charts) sont des patrons
> déjà implémentés (dashboard event-driven, catalogue, TUI, lib de charts).

## Pépites NOUVELLES trouvées dans les READMEs réels (gratuites, paper)

### 01 CloddsBot (README réel)
- **Ollama = LLM 100% LOCAL et GRATUIT** (listé parmi 8 providers). → couche IA gratuite
  possible : explainer offline « pourquoi ce wallet a bougé », résumé du ledger,
  narration des décisions. OFFLINE, jamais dans le hot-path, dégradation gracieuse si absent.
- **Trade Ledger : `clodds ledger calibration`** = accuracy par bucket de confiance +
  **block-reasons stats** + intégrité SHA-256. → rapport de calibration explicite.
- **Risk engine** : circuit breaker + **VaR/CVaR** + **vol regime** + **stress testing** +
  Kelly + daily loss + **kill switch**. (modules déjà codés mais dormants → câbler + panel)
- **Skills lazy-loaded** (dépendance manquante ne crashe pas). **Context compacting** (résumé
  des vieux messages). **Smart routing** (meilleur prix/liquidité/frais).
- BAN (et/ou payant) : x402 payments, token launch, marketplace, Bittensor, LLM cloud payant.

### 09 mlmodelpoly (README réel)
- Modules : pipeline/features/bars/edge_engine/fair_model/bias_model/volatility/
  **accumulate_engine**/decision_logger/http_api/metrics.
- **accumulate_engine** = accumulation par TRANCHES + caps `MAX_SLICES_PER_WINDOW=30`,
  `MAX_USD_PER_WINDOW=300`, `COOLDOWN_SEC`, `EDGE_BUFFER_BPS=25`. → discipline anti-churn.
- Features : CVD, RVOL, impulse, microprice, **basis (perp vs spot/oracle)**, anchored VWAP,
  liquidation tracking ; **fair_model fast/smooth** ; **bias multi-TF (CONTEXT_TFS 1m/5m/15m/1h)** ;
  **volatility fast/slow/blend sigma** ; **Quality Mode OK/DEGRADED/BAD** ; gates `MIN_DEPTH=200`,
  `MAX_SPREAD_BPS=500`, `STALE=5s` ; endpoints `/latest/features|bars|edge|state|health`.
- **TAAPI.io = PAYANT → EXCLU** (free only). Binance latency arb → EXCLU (hors HL).

### 10 polyrec (README réel)
- **eat-flow** (volume qui « mange » les niveaux du carnet) — feature microstructure NOUVELLE.
- **replicate_balance.py** = répliquer le **solde/allocation** du leader (pas juste les trades).
- fade_impulse backtest + visualisation. 70+ colonnes CSV (returns, ATR multi-fenêtres, rvol,
  spread, imbalance, microprice, slope). **oracle vs prix : lag/basis**.

### 11 prediction-market-backtesting (README réel)
- **Execution modeling profond** : Fees + **maker rebates**, slippage, **passive orders & queue
  position**, latency, limits, **vendor L2 behavior**. → edge net honnête.
- **Charts** : equity (total + **par marché**), PnL ticks, PnL periodic bars, **market allocation**,
  drawdown, **Sharpe ombré**, cash/equity, **monthly returns**, **cumulative Brier advantage**.
- **Account Ledger Replay → Copy-Trading Interpretation** + section **« Why Exact Reproduction
  Fails »** (honnêteté : latence/slippage/queue cassent la repro exacte).
- Research : scoring, **joint-portfolio multi-replay**, samplers random-grid + **TPE (Optuna)**,
  **CAVEATS anti-overfit**. + **AGENTS.md** (consignes agent) + **CODEBASE_UML / mermaid**.
- Licences MIXTES (GPL/LGPL/MIT) → idées/architecture uniquement, AUCUN code copié.

### 02 Harrier (README réel)
- **On-Chain Whale Signal 3–30 s d'avance** (décodage blocs/calldata) → chez nous : firehose
  fills WS bruts = source d'entrée la plus fraîche. **OBI** signal autonome (refresh ~500 ms).
- **Depth Guard : valider la liquidité du carnet AVANT CHAQUE entrée** (pas juste un score).
- Circuit breaker (N gros trades/fenêtre), Trade Floor (taille mini anti-EV-négatif), Dry-Run.
- Semaphore rate-limit 25 req/10 s. Stratégies : Direction (5m/15m auto TP+SL), Spread farming.

### 03 MrFadiAi (README réel)
- Loss halts EXACTS : daily 5% (pause 60 min), monthly 15% (30 j), drawdown 25% (7 j),
  **total 40% = halt permanent**. Smart-money : WR≥60 / PnL≥500 / PF≥1.5 / consistency≥70 /
  one-big-win≤30%. Sizing : base 2%, **−20%/perte consécutive, +10%/gain, cap 5%**.
- **DipArb** : chute panique >15% en 3 s → entrée + **hedge** côté opposé. Trade floor $1.50.
- Direct : FOK, SL 15% / TP 25% / max-hold 7 j. Dashboard risk panel (BREACHED/OK, streak).

### 04 polymarket_lp_tool (README réel) — maker/LP en SIMULATION
- **Reward-band repricing** : demi-largeur d'incitation δ ; `distance_ratio=|px−mid|/δ` :
  **[0.4,0.6] keep / <0.4 move-out / >0.6 move-in** ; classification tick coarse/fine ;
  **min-replace-ticks** ; **skip token si position déjà ouverte** (inventory-aware).
  → modèle de QUALITÉ d'exécution maker / positionnement vs mid (paper, jamais d'ordre).

### 12 polybot (README réel)
- **replication & similarity scoring** + **execution-quality analysis** (research/). Mode défaut
  `hft.mode: PAPER`. `/actuator/health` par service + `SELECT 1` DB-ping. (Java/Kafka/ClickHouse
  = DEFER ; on garde les concepts en Python/SQLite.)

## Décision : nouvelles étapes #154→#163 (toutes GRATUITES, paper-only)
Voir progression. Axe central inchangé : **moins de trades, plus propres + IA locale gratuite**.
Tout ce qui touche maker/LP, accumulate, hedge reste de la **simulation de qualité d'exécution** :
zéro ordre réel, zéro clé, zéro signature, zéro API/donnée payante.

## Balayage 14/14 — les 4 derniers (05, 07, 08, 14)

### 05 PolyWeather (README réel) — PÉPITE calibration
- **EMOS/CRPS calibration** (Ensemble Model Output Statistics + Continuous Ranked Probability
  Score) : calibration de proba rigoureuse, **gratuite**, entraînée OFFLINE sur une copie SQLite,
  avec discipline **`legacy` → `emos_shadow` → `emos_primary`** et **promotion seulement si
  `ready_for_promotion=true`**. C'est exactement notre shadow→autoritatif, en plus rigoureux.
- **DEB (Dynamic Error Balancing)** : blend multi-modèles **pondéré par l'erreur récente** de
  chacun → down-weight ce qui se trompe. Transposable : ensemble de signaux/stratégies pondéré
  par leur Brier/erreur réalisée récente (gratuit, local, nourrit l'opportunity_ranker).
- **model-market difference = P(modèle) − P(marché)** = notre edge ; SSE patches + replay (déjà).
- Observabilité `/healthz` `/api/system/status` `/metrics` (déjà). Météo/METAR/TAF = N/A perps.

### 07 Awesome PM Tools (catalogue) + 08 PolyTerm + 14 lightweight-charts
- Catégories confirmées (déjà couvertes) : analytics, dashboards, copy-trading, wallet/leaderboard,
  alerting (off), tracking, orderbook/microstructure, backtest. PolyTerm confirme : EV, Kelly,
  screener/presets, export CSV/JSON, SQLite, paper (tout déjà prévu #138/#151).
- **Alt-data sentiment/news/Twitter/odds** (Awesome) : sources gratuites peu fiables ou payantes
  (Twitter API payant) → **DEFER**, hors cœur copy-trading. Pas de dépendance payante.
- 14 lightweight-charts : déjà implémenté (#131).

## Étapes ajoutées par le balayage 14/14
- #164 Calibration rigoureuse EMOS/CRPS + reliability diagram + promotion gate (`ready_for_promotion`).
- #165 DEB ensemble pondéré par l'erreur récente (down-weight les signaux qui se trompent).

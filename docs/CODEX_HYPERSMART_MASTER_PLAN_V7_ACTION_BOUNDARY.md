
# CODEX_HYPERSMART_MASTER_PLAN_V7_ACTION_BOUNDARY

> **IMPORTANT — CETTE V7 REMPLACE LA LECTURE TROP STRICTE DE LA V6.**
>
> Ne supprime rien de la V6. Mais à partir de maintenant, toutes les anciennes interdictions doivent être interprétées avec cette règle centrale :
>
> ## La seule interdiction absolue est : aucune action réelle externe.
>
> HyperSmart doit rester **simulation locale / paper / mock USDC**.  
> Tout ce qui est **recherche, scraping public, Browser, lecture API, lecture GitHub, lecture docs, lecture dashboards publics, parsing HTML, import CSV/JSON, stockage local, simulation locale, paper trading local, backtest local, dashboard local, génération de rapports, écriture SQLite locale** est autorisé si cela ne déclenche aucune action réelle sur une plateforme externe.

---

## 0A. Simulation officielle unique à préserver

HyperSmart ne doit pas créer une deuxième simulation, un mode démo de remplacement, un fallback artificiel, une simulation "au cas où", ni un graphe parallèle.

La simulation officielle unique du projet est celle déjà utilisée par l'utilisateur :

```text
LANCER_HYPERSMART.cmd
-> tools/start_hypersmart_simulation.ps1
-> src/hl_observer/ui/static/simulation_v2.html
-> /api/simulation/status
-> /api/simulation/overview
-> UiState persistant
-> runtime/data/hypersmart_simulation_session.sqlite3
-> PaperEngine / portefeuille paper existant
```

Règle obligatoire :

- garder cette simulation comme interface principale ;
- améliorer cette simulation existante, ne jamais la remplacer ;
- brancher cette simulation sur les prix et événements Hyperliquid read-only ;
- si aucune opportunité exploitable n'est détectée, afficher un état vide honnête, pas une position inventée ;
- si une position paper locale existe, le PnL latent doit être recalculé avec les derniers prix Hyperliquid disponibles (`allMids`, `publicTradesWS`, `l2Book`/mid si disponible) ;
- le métagraphe doit afficher uniquement l'equity/PnL de cette simulation existante ;
- le graphe peut être plus fluide visuellement, mais il ne doit jamais créer de faux mouvement ;
- aucun agent ne doit ajouter une nouvelle page de simulation, un nouveau portefeuille fictif parallèle, un nouveau moteur de PnL parallèle ou une source de faux trades.

Le fichier `runtime/data/hypersmart_engine_status.json`, s'il existe, est seulement un heartbeat/diagnostic du moteur. Il ne doit jamais devenir une source de PnL, de position, de trade ou de décision. Le PnL vient uniquement de la simulation paper existante et des prix Hyperliquid read-only.

Tests attendus quand cette zone est touchée :

- `test_paper_engine_existing_simulation_not_replaced.py`
- `test_ui_simulation_status_fast.py`
- `test_no_fake_chart_or_fake_position_data.py`
- un test prouvant que `/api/simulation/status` mark-to-market les positions ouvertes avec les prix Hyperliquid stockés localement ;
- un test prouvant qu'en absence de signal exploitable, aucune position de secours n'est créée.

---

## 0. Pourquoi cette V7 existe

La V6 était trop stricte dans certaines formulations. Elle pouvait bloquer Claude/Codex parce qu'elle disait parfois "BAN" sur des mots ou familles entières comme `scraping`, `CLOB`, `Polymarket`, `Kalshi`, `ethers`, `buy`, `sell`, `copy`, `trade`, `subprocess`, `write tools`, alors que plusieurs GitHub utiles utilisent ces notions comme **sources d'idées**, **formats de données**, **read-only research**, **tests**, ou **simulation locale**.

Cette V7 corrige cela.

À partir de maintenant :

- `trade`, `buy`, `sell`, `copy`, `order`, `CLOB`, `Polymarket`, `Kalshi`, `ethers`, `dYdX`, `scraper`, `browser`, `crawler`, `subprocess`, `write`, `close`, `execute` ne sont pas automatiquement interdits.
- Ils sont interdits seulement s'ils déclenchent ou préparent une **action réelle externe**.
- Ils sont autorisés dans :
  - docs ;
  - tests ;
  - analyse GitHub ;
  - parsing de données publiques ;
  - modèles de simulation ;
  - paper trades locaux ;
  - backtests ;
  - UI de simulation clairement marquée ;
  - rapports ;
  - connecteurs read-only ;
  - outils locaux de développement.

---

## 1. Nouvelle règle de sécurité unique

### 1.1 Hard ban réel

Sont toujours interdits :

- envoyer un ordre réel ;
- annuler un ordre réel ;
- modifier un ordre réel ;
- signer une transaction réelle ;
- transférer des fonds ;
- retirer des fonds ;
- déposer des fonds ;
- utiliser ou demander une private key ;
- connecter un wallet réel ;
- utiliser un secret pour agir ;
- contourner une protection de plateforme ;
- faire du scraping derrière login/paywall/captcha sans autorisation ;
- automatiser une action financière externe ;
- écrire dans une API de trading externe ;
- activer un executor réel.

### 1.2 Tout le reste peut être utilisé si local ou read-only

Sont autorisés :

- scraping public raisonnable ;
- Browser ;
- crawl GitHub/docs ;
- lecture de pages publiques ;
- parsing HTML public ;
- lecture API read-only ;
- WebSocket read-only ;
- import CSV/JSON/TXT ;
- index local ;
- cache local ;
- SQLite local ;
- write local files ;
- subprocess pour tests/scripts locaux ;
- scripts PowerShell/Python de dev ;
- dashboard local ;
- export HTML/CSV/JSON ;
- paper trades locaux ;
- boutons UI de simulation locale s'ils sont très clairement marqués `SIMULATION ONLY`;
- local close/reduce paper position ;
- local reset paper portfolio avec confirmation + backup ;
- local config editor avec backup ;
- agent tools write-local si jamais ils ne touchent qu'au projet local.

---

## 2. Changement obligatoire de vocabulaire pour Codex/Claude

Remplacer les anciens "BAN" trop larges par ces catégories :

```text
BAN_REAL_ACTION
READ_ONLY_ALLOWED
SIMULATION_ALLOWED
LOCAL_WRITE_ALLOWED
RESEARCH_ONLY_ALLOWED
DEFER_SCALE
```

Exemples :

| Ancien terme | Nouvelle interprétation |
|---|---|
| Polymarket | RESEARCH_ONLY_ALLOWED sauf runtime trading |
| Kalshi | RESEARCH_ONLY_ALLOWED sauf runtime trading |
| CLOB | READ_ONLY_ALLOWED si analyse de données, BAN_REAL_ACTION si order placement |
| ethers | READ_ONLY_ALLOWED si lecture publique, BAN_REAL_ACTION si signer/envoyer |
| trade | SIMULATION_ALLOWED si paper, BAN_REAL_ACTION si vrai ordre |
| buy/sell | SIMULATION_ALLOWED dans PaperEngine, BAN_REAL_ACTION sur API externe |
| copy | SIMULATION_ALLOWED pour copy-wallet paper, BAN_REAL_ACTION pour copy-trading réel |
| execute | LOCAL_WRITE_ALLOWED pour scripts/tests, BAN_REAL_ACTION pour ordre réel |
| scraper | READ_ONLY_ALLOWED si public/rate-limited, interdit si bypass |
| write tool | LOCAL_WRITE_ALLOWED si fichier/SQLite local, BAN_REAL_ACTION si API externe |
| subprocess | LOCAL_WRITE_ALLOWED pour tests/outils locaux, interdit si destructeur/non borné |
```

---

## 3. Scraping / Browser / OSINT — autorisé et même demandé

### 3.1 But

Codex et Claude doivent pouvoir chercher les meilleures idées dans les GitHub, les docs, les dashboards publics, les sources Hyperliquid publiques et les pages publiques utiles.

### 3.2 Sources autorisées

- GitHub publics.
- README/docs/issues/tests publics.
- Docs officielles Hyperliquid.
- Pages publiques d'analytics Hyperliquid si accessibles publiquement.
- Leaderboards publics : collecte via scraping + proxies/rotation autorisee (cf. V9 §8).
- Exports CSV/JSON publics.
- Fichiers fournis par l'utilisateur.
- Pages publiques de documentation technique.
- API publiques read-only.

### 3.3 Règles d'un scraper propre

Créer éventuellement :

- `research_scraper/`
- `source_registry/`
- `public_web_fetcher.py`
- `github_repo_researcher.py`
- `html_parser.py`
- `rate_limiter.py`
- `cache.py`
- `provenance.py`

Chaque source doit avoir :

```text
source_id
url
source_type OFFICIAL_DOC|GITHUB|PUBLIC_HTML|PUBLIC_API|USER_FILE|MANUAL_IMPORT
allowed_use READ_ONLY_RESEARCH|SEED_DISCOVERY|BENCHMARK|DOC_ONLY
requires_login boolean
robots_checked boolean if automated crawling
rate_limit_policy
cache_ttl
last_fetch_ts
raw_hash
parsed_hash
provenance
```

### 3.4 Politique scraping (AUTORISEE — amendee 2026-06-19)

- pas de bypass login ;
- pas de captcha bypass ;
- pool de proxies + rotation AUTORISE (datacenter/residentiel/mobile, cf. AGENTS.md / V9 §8) ;
- scraping public AUTORISE (budget de poids par IP, backoff, circuit breaker) ;
- pas de données privées ;
- pas d'usurpation de session ;
- pas d'écriture sur le site ;
- donnees publiques uniquement (aucune action/ecriture argent-reel sur le site) ;

### 3.5 Tests scraping

Créer/renforcer :

- `test_research_scraper_public_only.py`
- `test_scraper_respects_rate_limit.py`
- `test_scraper_blocks_login_required_sources.py`
- `test_scraper_stores_provenance.py`
- `test_scraper_cache_prevents_refetch_spam.py`
- `test_github_researcher_extracts_keep_adapt_defer.py`

---

## 4. Polymarket/Kalshi/dYdX ne sont plus "bannis" comme sources

### 4.1 Nouvelle règle

On ne bannit pas les idées ni les données publiques. On bannit uniquement les actions réelles.

### 4.2 Autorisé

- lire les dépôts Polymarket/Kalshi ;
- analyser leurs architectures ;
- importer des concepts ;
- créer des modèles inspirés ;
- créer des connecteurs read-only de recherche si utiles ;
- parser des données publiques pour benchmark ;
- comparer les patterns à Hyperliquid ;
- créer des tests avec fixtures Polymarket/Kalshi comme exemples non runtime.

### 4.3 Interdit

- ordre réel Polymarket/Kalshi ;
- CLOB order placement ;
- API key de trading ;
- wallet signing ;
- proxy wallet ;
- buy/sell real ;
- live trading.

### 4.4 dYdX

dYdX peut rester dans le repo comme :

- module secondaire ;
- benchmark ;
- mockable adapter ;
- future research path.

Mais HyperSmart runtime par défaut reste Hyperliquid.

---

## 5. Boutons et UI : autoriser la simulation locale

La V6 a trop fortement interdit certains boutons. Nouvelle règle :

### Autorisé dans UI locale si clair

- `Start simulation`
- `Stop simulation`
- `Run scanner`
- `Run backtest`
- `Replay`
- `Export`
- `Archive`
- `Open paper position details`
- `Close paper position locally`
- `Reset paper portfolio` avec confirmation + backup
- `Acknowledge risk event`
- `Filter`
- `Sort`
- `Search`
- `Toggle`
- `Mark watchlist`
- `Import CSV`
- `Load fixtures`

### Interdit dans UI

- `Send real order`
- `Connect wallet`
- `Sign`
- `Deposit`
- `Withdraw`
- `Place order on Hyperliquid`
- `Place order on Polymarket`
- `Enable live trading`
- `Use private key`

Règle : un bouton est dangereux seulement s'il agit hors du système local.

---

## 6. Agent tools : autoriser write-local

La V6 disait parfois "read-only tools only". C'est trop restrictif pour un agent de codage.

### 6.1 Tools d'agent système

Pour les agents de codage, ils peuvent :

- lire fichiers ;
- modifier fichiers ;
- créer fichiers ;
- créer tests ;
- lancer pytest ;
- lancer scripts locaux ;
- écrire SQLite locale ;
- créer archives ;
- générer dashboard HTML ;
- générer rapports MD/JSON/CSV.

### 6.2 Tools exposés dans le produit

Dans le produit HyperSmart final, distinguer :

#### Outils read-only publics

- status.read
- wallet.leaderboard
- decision_ledger.search
- dashboard.export
- source_health.read

#### Outils local-simulation write

- simulation.start
- simulation.stop
- simulation.reset_with_backup
- paper_position.close_local
- backtest.run
- archive.create_clean
- research.rescan_sources
- watchlist.import_local

Tous ces outils doivent être **local only**.

### 6.3 Tests

- `test_local_write_tools_do_not_call_external_trade_api.py`
- `test_simulation_buttons_are_labeled_local_only.py`
- `test_reset_requires_backup_and_confirmation.py`
- `test_agent_tools_cannot_access_private_keys.py`

---

## 7. Audits sécurité : remplacer les scans de mots par des scans de contexte

Les audits qui bloquent simplement les mots `buy`, `sell`, `trade`, `copy`, `CLOB`, `Polymarket`, `ethers`, `execute` sont mauvais.

### 7.1 Nouveau comportement

Un audit doit classifier :

- `DOC_ONLY`
- `TEST_ONLY`
- `SIMULATION_ONLY`
- `LOCAL_TOOL`
- `READ_ONLY_RESEARCH`
- `DANGEROUS_EXTERNAL_ACTION`

### 7.2 Danger réel

Le danger existe si :

- HTTP POST vers endpoint externe de trading ;
- appel SDK order/cancel/modify ;
- signing ;
- private key ;
- nonce/action ;
- wallet connect ;
- mutation externe ;
- executor loop externe ;
- live flag qui active une mutation externe.

### 7.3 Toléré

- texte d'interdiction ;
- test de sécurité ;
- doc de recherche ;
- paper trade local ;
- paper buy/sell local ;
- fake fixtures de tests ;
- scraper public read-only ;
- read-only API.

### 7.4 Tests

Créer :

- `test_audit_allows_simulation_terms.py`
- `test_audit_allows_research_only_polymarket_mentions.py`
- `test_audit_flags_external_order_post.py`
- `test_audit_flags_private_key_usage.py`
- `test_audit_context_classification.py`

---

## 8. Backtest et PaperEngine : ne pas bloquer les actions simulées

Dans la simulation, il faut autoriser :

- simulated open ;
- simulated add ;
- simulated reduce ;
- simulated close ;
- simulated buy/sell labels ;
- simulated order model ;
- simulated fills ;
- simulated slippage ;
- simulated liquidation event ;
- simulated funding ;
- simulated margin ;
- simulated PnL.

Mais chaque objet doit porter :

```text
simulation_only = true
not_an_order = true
external_action = false
venue_mutation = false
```

Tests :

- `test_paper_trade_is_marked_not_order.py`
- `test_simulated_order_model_never_calls_exchange.py`
- `test_paper_close_is_local_only.py`

---

## 9. GitHub ideas à récupérer plus librement

Codex doit relire les GitHub avec cette nouvelle grille :

- ne plus classer une idée comme BAN parce qu'elle vient de Polymarket ;
- ne plus ignorer une idée parce qu'elle parle de trade ;
- extraire le concept ;
- retirer seulement la partie action réelle ;
- reconstruire en Hyperliquid local simulation.

Exemples :

| GitHub | Idée originale | Adaptation HyperSmart |
|---|---|---|
| CloddsBot | agent trading + ledger | autonomous local researcher + decision ledger |
| Harrier | execution strategies | simulation strategies + risk layer |
| MrFadi | copy bot filters | wallet score + copyability + paper sizing |
| lp_tool | order manager | no order manager, but mid stability + cooldown + reconcile |
| PolyWeather | event UI | authoritative dashboard + stale state |
| Composio | buy Polymarket late | timing gates + current_signal/no_trade only |
| PolyTerm | trade journal | paper journal + decision search |
| mlmodelpoly | fair model/edge | edge estimate local |
| polyrec | huge CSV | scan_features Hyperliquid |
| backtesting | book replay | fills/books replay Hyperliquid |
| polybot | executor services | DEFER architecture, no executor |
| agents | autonomous agent | research/evidence agent, no trade |
| Lightweight | charts | real dashboard charts |

---

## 10. Prompt court Codex recommandé avec V7

```text
Lis docs/CODEX_HYPERSMART_MASTER_PLAN_V7_ACTION_BOUNDARY.md. Cette V7 assouplit les anciennes interdictions: seule l'action réelle externe est interdite. Autorise scraping public, Browser, read-only APIs, recherche Polymarket/Kalshi/GitHub, write-local tools, PaperEngine et boutons de simulation locale. Travaille local only dans C:\Users\flo\Desktop\Projet invest. Ne supprime rien. Runtime par défaut Hyperliquid, simulation locale only. Reprends le plan V6 avec cette nouvelle grille, corrige les audits trop stricts, puis avance sur la prochaine vertical slice complète: PositionLifecycle+ExitEngine+PaperEngine reduce/close+PnL+Evidence+Dashboard+Backtest. Tests+safety+rapport FR.
```

---

## 11. Phrase de doctrine finale

> **Tout est autorisé si c'est lecture publique, recherche, simulation locale, test, backtest, dashboard local ou écriture locale contrôlée. La seule frontière dure est : aucune action réelle externe, aucune clé privée, aucune signature, aucun ordre réel.**

---

# HISTORIQUE V6 CONSERVÉ CI-DESSOUS

Le contenu V6 original est conservé après cette section. Si une phrase de la V6 semble plus stricte que la V7, la V7 gagne.


# CODEX_HYPERSMART_MASTER_PLAN_V6.md

**Projet : HyperSmart Observer**  
**But : smart-wallet observer / copy-wallet simulator Hyperliquid-only, en simulation paper/mock USDC.**  
**Dossier local cible :** `C:\Users\flo\Desktop\Projet invest`  
**Usage :** source de vérité longue pour Codex. Le mode Objectif doit rester court et dire à Codex de lire ce fichier, puis d'appliquer la prochaine priorité non terminée.

---

## 0. Objectif court Codex recommandé

```text
Lis docs/CODEX_HYPERSMART_MASTER_PLAN_V6.md et AGENTS.md si présent. Utilise Browser pour revérifier tous les GitHub et docs Hyperliquid listés. Travaille local only dans C:\Users\flo\Desktop\Projet invest. Ne supprime rien. Applique la prochaine priorité non terminée du plan avec code réel, tests, safety-check, audit-safety et rapport final FR. Préserve PaperEngine/simulation/launcher/tests, garde dYdX isolé, bannis Polymarket runtime et /exchange.
```

---

## 1. Règles non négociables

1. **Ne rien supprimer brutalement.** Ne pas effacer historique, simulation, tests, launcher, docs, dYdX WIP ou exports utiles sans backup + validation manuelle.
2. **Runtime principal Hyperliquid-only.** Utiliser uniquement `/info` + WebSocket read-only pour le runtime.
3. **Simulation-only.** Paper/mock USDC uniquement. Aucune exécution réelle.
4. **Polymarket/Kalshi = benchmarks d'idées uniquement.** Aucun runtime, adapter, CLOB, wallet, endpoint ou dépendance Polymarket/Kalshi actif.
5. **dYdX = secondaire/mockable/isolé.** Ne pas lancer/importer dYdX par défaut dans le runtime Hyperliquid.
6. **Simulation existante = cœur du projet.** Ne pas créer un PaperEngine parallèle si un simulateur existe déjà. Le brancher et l'améliorer.
7. **No fake data.** Dashboard, PnL, chart, position, signal doivent venir de données réelles read-only ou d'état vide propre.
8. **Pas de promesse de profit.** Le logiciel mesure la simulation, il ne garantit rien.

---

## 2. Bannissements absolus à auditer partout

Chercher dans `hyper_smart_observer/`, `src/hl_observer/`, `templates/`, `static/`, JS/TS, `tools/`, scripts, docs, routes, handlers, launchers, tests :

- `/exchange` opérationnel ;
- Hyperliquid Exchange SDK opérationnel ;
- `place_order`, `cancel`, `modify`, `order`, `trade`, `execute`, `buy`, `sell`, `copy` si c'est relié à une action réelle ;
- signatures, nonce/action signing, private key, seed, wallet connect, real balance ;
- Polymarket CLOB, `@polymarket/clob-client`, `buy_polymarket`, `ethers` pour trader ;
- live toggle, executor-service, mainnet/testnet execution ;
- fake chart, fake position, fake PnL, seeded demo trade dans dashboard ;
- bouton UI dangereux : Buy/Sell/Trade/Copy/Execute/Connect Wallet ;
- secrets dans logs/html/js/docs ;
- promesse de profit.

Les mots dangereux peuvent exister dans docs/tests seulement si le contexte est BAN/AUDIT/SAFETY et testé.

---

## 3. Hyperliquid official contract à respecter

Docs à revérifier avec Browser :

- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint

À modéliser côté read-only :

- `allMids` ;
- `l2Book` ;
- `clearinghouseState` ;
- `userFills` ;
- `userFillsByTime` ;
- `openOrders` et `frontendOpenOrders` comme contexte uniquement ;
- `orderStatus` uniquement diagnostic, jamais preuve suffisante ;
- `candleSnapshot` ;
- WS `allMids`, `userFills`, `userEvents`, `openOrders`, `clearinghouseState`, `l2Book`, `trades`, `bbo`.

Contraintes à tester :

- `/info` time-range : pagination 500 éléments/blocs distincts, next `startTime` = dernier timestamp + garde anti-boucle ;
- `userFills` / `userFillsByTime` : fenêtres bornées, metadata `window_complete`, `truncated`, `oldest_available_ts`, `stopped_reason`, `aggregate_by_time_used` ;
- `allMids` : peut fallback sur last trade if book empty, donc `mid_source` + `data_quality` obligatoires ;
- `l2Book` : profondeur limitée, utile pour spread/liquidity/microprice/depth imbalance, pas pour promesse d'exécution profonde ;
- WS : snapshots `isSnapshot:true`, updates ensuite ; dédup snapshot/update ;
- Rate limits : REST budget, poids par items, WS max 10 connections, 1000 subs, 10 unique user-specific users ;
- Architecture obligatoire : REST broad scan/backfill -> WalletScore/shortlist -> WS max 10 wallets -> REST reconciliation.

---

## 4. Launcher officiel à préserver

`LANCER_HYPERSMART.cmd` contient les garde-fous à conserver et à aligner avec `tools/start_hypersmart_simulation.ps1` :

- `HL_ENV=paper`
- `HL_ENABLE_MAINNET_EXECUTION=0`
- `HL_ENABLE_TESTNET_EXECUTION=0`
- `HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW`
- `HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW=1`
- `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=6000`
- `HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY=0`
- `HYPERSMART_SIMULATION_MIN_EDGE_BPS=35`
- `HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE=0.5`
- `HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=12`

Ces valeurs doivent piloter `run_copy_dry_run`, `SignalCandidate`, `EdgeCalculator`, `RiskEngine`, `PaperEngine`, dashboard et tests. dYdX variables in launcher are WIP secondary; do not let them override HyperSmart guards.

---

## 5. État actuel présumé à vérifier avant chaque sprint

Vérifier sans refaire inutilement :

- `run_copy_dry_run` construit `market_features_by_coin` depuis `allMids + l2Book` ;
- `detect_signal_candidates` reçoit les vraies features ;
- gates testées : low liquidity, wide spread, missing l2Book, edge missing/too low ;
- `feature_hash` existe dans `MarketSignalFeatures` / export ;
- helper `volatility.py` existe mais `volatility_context` live peut rester à brancher ;
- `PaperTradingSimulator` existe ;
- PnL/equity/drawdown dashboard existent ;
- dYdX n'est pas importé par défaut ;
- sécurité OK via safety/audit.

Si un item est faux dans le repo local, corriger la roadmap en rapport final.

---

## 6. GitHub à revérifier avec Browser avant de coder

Codex doit ouvrir README/docs/src/tests quand disponibles. Ne pas copier le code : extraire idées, risques, modules cibles, tests.

### 6.1 CloddsBot
URL : https://github.com/alsk1992/CloddsBot

KEEP : dashboard/WebChat local read-only, Reports/Artifacts/Diagnostics, doctor/secure CLI, market data layer, risk engine, backtesting, decision ledger, confidence calibration, SHA-256, whale/copy tracking, telemetry, local persistence, modular docs/scripts/src/tests.

ADAPT_TO_HYPERLIQUID : dashboard premium HyperSmart, DecisionLedger append-only, source_health panel, doctor/safety checks, whale/copy wallet observer, report artifacts, local history/search.

BAN : execution, credentials setup, live trading, smart routing, payments, token launch, marketplace, autonomous trade actions.

### 6.2 Harrier / Prediction-Markets-Trading-Bot-Toolkits
URL : https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits

KEEP : common core, risk layer, venue adapters, dry-run idea, circuit breaker, depth guard, cooldown, min notional, venue-agnostic design.

ADAPT : “One observation/paper core. One risk layer. Every venue.” HyperliquidAdapter read-only, MockAdapter, dYdX secondary mockable, one RiskEngine.

BAN : execution core réel, FAK/GTD, market making, resolution sniper, sports execution, <50ms execution, live enable.

### 6.3 MrFadiAi/Polymarket-bot
URL : https://github.com/MrFadiAi/Polymarket-bot

KEEP : WalletScoreV2, CopyabilityScore, smart money filters, winrate, profit factor, consistency, one_big_win_ratio, pnl_concentration, min trade count, recent activity, risk halts mock 5/15/25/40, conservative paper sizing.

ADAPT : wallet intelligence, risk flags, mock portfolio halts, sizing only for simulation.

BAN : private key, live toggle, wallet verification réel, panic sell, real balances, auto-copy real.

### 6.4 polymarket_lp_tool
URL : https://github.com/lihanyu81/polymarket_lp_tool

KEEP : WS-first, REST reconciliation, deterministic rules, structured tracing/logging, source_health, midpoint jump filter, stable confirmation, EMA/median smoothing, cooldown, max chase/copy degradation, JSON persistence, dedupe.

ADAPT : Hyperliquid WS shortlist, `/info` reconciliation, mid_stability, cooldown wallet/symbol/action, copy_degradation guard.

BAN : OrderManager, cancel/repost/reprice, post-only, any order logic.

### 6.5 PolyWeather
URL : https://github.com/yangyuan-zhen/PolyWeather

KEEP : dashboard event-driven, authoritative snapshot, stale data blocked during refresh, fallback refresh, source_health, health/status/metrics, runtime data outside git, release/docs discipline.

ADAPT : DashboardPayload authoritative, stale_signal_not_paper_ready, source_health visible, fallback read-only refresh.

BAN : payments/onchain checkout/points.

### 6.6 Composio arbitrage bot
URL : https://github.com/Composio-HQ/polymarket-kalshi-arbitrage-bot

KEEP : `/health`, `/status`, scanner_running, polling loop, timing gate, spread/edge metrics, current_signal/no_trade.

ADAPT : local read-only status API/dashboard panel.

BAN : private key, proxy wallet, trade USD, buy_polymarket, tradingEnabled, CLOB, ethers.

### 6.7 Awesome Prediction Market Tools
URL : https://github.com/aarora4/Awesome-Prediction-Market-Tools

KEEP : product benchmark: analytics, dashboards, APIs, alerts, data, portfolio tracking, leaderboards, copyability, whale/smart/suspicious/fresh labels, live mids/spreads/liquidity/orderbook depth, historical snapshots.

ADAPT : dashboard and wallet intelligence benchmark for Hyperliquid.

BAN : one-click replication, wallet integrations, autonomous betting agents, fake/mockup products.

### 6.8 PolyTerm
URL : https://github.com/NYTEMODEONLY/polyterm

KEEP : agent-ready tooling, manifest, JSON Schemas, FastMCP-like read-only server, doctor diagnostics, `llms.txt`, `llms-full.txt`, read-only market/wallet tools, SQLite local state, exports JSON/CSV, historical replay, zero custody, input sanitization, no bare subprocess, graceful failure.

ADAPT : agent-safe read-only manifest: `status.read`, `wallet.leaderboard`, `decision_ledger.search`, `dashboard.export`, `source_health.read`, `archive.status`, `archive.search`.

BAN : write/trade tools, Kelly real sizing, execution links.

### 6.9 mlmodelpoly
URL : https://github.com/txbabaxyz/mlmodelpoly

KEEP : WS streams, OHLCV, CVD, VWAP, RVOL, impulse, microprice, basis, anchored VWAP, liquidation tracking, volatility, fair value/edge, REST `/latest/features`, `/latest/bars`, `/latest/edge`, decision_logger, metrics.

ADAPT : Hyperliquid `market_signal_features` from `allMids/l2Book/trades/candles`, not Binance/Polymarket.

BAN : Polymarket CLOB, TAAPI/Binance hot path dependency.

### 6.10 polyrec
URL : https://github.com/txbabaxyz/polyrec

KEEP : rich CSV/JSON exports, 70+ columns, orderbook levels, spread, imbalance, microprice, slope/depth_slope, returns, volume, ATR/RVOL, eat-flow/trade-flow analogue, backtesting tools.

ADAPT : Hyperliquid `scan_features`: timestamp/source_ts, wallet, symbol, current_mid, l2 levels, spread_bps, depth_imbalance, microprice, depth_slope, volatility_context, leader_delta, copy_degradation_bps, edge_remaining_bps, data_quality, source_health.

BAN : Chainlink/Binance/Polymarket runtime specifics, logs as primary DB.

### 6.11 prediction-market-backtesting
URL : https://github.com/evan-kolberg/prediction-market-backtesting

KEEP : custom adapters, staged data loading, materialized caches, unified cache/local/archive/API bus, book replay, orderbook deltas, trade ticks, equity/PnL/drawdown/Sharpe/monthly returns, fees/slippage/latency/liquidity/missed fills, no-trade analysis.

ADAPT : strict runtime/backtest/paper parity.

BAN : copying code, mixed-license contamination, live sandbox execution.

### 6.12 polybot
URL : https://github.com/ent0n29/polybot

KEEP/DEFER : ingestion/strategy/analytics/monitoring separation, replication scoring, calibration, research snapshots, simulation-quality analysis.

DEFER : ClickHouse, Redpanda/Kafka, Grafana, Prometheus, microservices.

BAN : executor-service, live mode, private keys, market making.

### 6.13 Polymarket/agents
URL : https://github.com/Polymarket/agents

KEEP : research layer offline only, connectors, Pydantic, RAG/evidence reports, vector DB idea.

BAN : signing, CLOB, trading, private key, autonomous orders, `trade.py` operational.

### 6.14 Lightweight Charts
URL : https://github.com/tradingview/lightweight-charts

KEEP : performant HTML5 financial charts.

ADAPT : real paper equity, edge_remaining, latency, spread/liquidity, lifecycle, drawdown, backtest charts.

BAN : fake movement, generated demo chart pretending live data.

---

## 7. Architecture cible

Si modules existent, renforcer sans dupliquer.

- `hyperliquid_client/`: read-only `/info`, WS client, rate limiter, payload validation, no `/exchange`.
- `venues/`: BaseAdapter, HyperliquidAdapter read-only, MockAdapter, dYdX secondary mockable.
- `pipeline/`: CollectionRun, SourceHealth, cursors, fill_dedupe, snapshot_writer, REST reconciler.
- `models/`: Common Data Model with schema_version/adapter_version/data_quality.
- `market_signals/`: mid_stability, orderbook_features, volatility, liquidity_score, copy_degradation, edge_calculator, scan_features export.
- `wallet_intelligence/`: WalletScoreV2, CopyabilityScore, risk flags, labels, leaderboard.
- `position_lifecycle/`: fill grouping, open/add/reduce/close/flip episodes, confidence.
- `copy_mode/`: delta_detector, signal_candidate, no_trade_report, reason_codes.
- `risk_engine/`: deny-by-default gates, circuit breaker, cooldown, mock halts.
- `paper_trading/`: existing simulator, PaperIntent, PaperTrade, PnL, equity, drawdown, mock USDC.
- `exit_engine/`: reduce/close follow, stops, trailing, MAE/MFE, notional caps.
- `decision_ledger/`: append-only decisions, evidence_chain, hashes.
- `dashboard/`: read-only payload/export/event stream, no fake data.
- `backtesting/`: replay engine using same runtime models.
- `agent_tools/`: read-only manifest and schemas.
- `audit/`: safety, runtime hygiene, archive readiness, bounded walk.

---

## 8. Common Data Model minimum

Every important object should include:

- `venue`
- `source_endpoint` or `source_channel`
- `source_ts`
- `local_received_ts`
- `latency_ms`
- `raw_ref` or `raw_hash`
- `data_quality`
- `is_stale`
- `schema_version`
- `adapter_version`

Models to create/strengthen:

- NormalizedFill
- NormalizedPosition
- NormalizedOpenOrder
- MarketMid
- OrderBookSnapshot
- MarketSignalFeatures
- WalletSnapshot
- CollectionRun
- SourceHealth
- LeaderDelta
- PositionEpisode
- SignalCandidate
- NoTradeDecision
- RiskDecision
- PaperIntent
- PaperTrade
- DecisionLedgerEntry
- DashboardEvent
- BacktestEvent

---

## 9. Roadmap priorisée

### P0 — Vérification courte avant chaque sprint

Run:

- `git status --short`
- `git diff --stat`
- tests ciblés existants
- `--safety-check`
- `--audit-safety`

Do not spend the whole session auditing old work; only verify enough to avoid regressions.

### P1 — EvidenceChain / DecisionLedger real link

Current minimal state may be `feature_hash` in scan_features export. Upgrade to auditable ledger:

- `decision_id` -> `feature_hash`
- source_health refs
- raw refs allMids/l2Book/candles/fills
- `signal_candidate_id`, `no_trade_id`, `paper_intent_id`, `paper_trade_id`
- reason_codes
- snapshot hashes
- reproducible SHA-256

Tests:

- decision can find exact feature row/hash
- hash reproducible
- no decision without evidence minimum
- no fake refs

### P2 — Volatility live from candleSnapshot/trades

Add read-only `candleSnapshot` and/or trades support if absent.

Compute:

- `realized_vol_bps`
- `range_bps`
- `atr_bps` if possible
- `volatility_bucket` LOW/NORMAL/HIGH/EXTREME
- `data_quality`
- source refs

If data absent, keep `None`/degraded. Never invent.

Tests:

- valid candles -> non-null context
- absent candles -> degraded/None
- extreme volatility -> risk flag or NoTrade if policy exists

### P3 — Position lifecycle Hyperliquid

Use fill fields:

- `dir`
- `startPosition`
- `closedPnl`
- `fee`
- `feeToken`
- `hash`
- `oid`
- `tid`
- `crossed`
- `liquidation`
- `builderFee`

Reconstruct:

- open/add/reduce/close/flip
- partial fills
- partial closes
- average entry/exit
- holding time
- realized leader PnL
- lifecycle confidence

Ambiguous lifecycle => NoTrade, never PaperIntent.

### P4 — Exit engine local simulation

Paper-only engine for:

- follow leader reduce/close
- partial close
- no matching paper position => NoTrade
- time stop
- trailing stop
- max MAE/MFE
- max holding time
- max open positions
- blocked assets
- notional cap
- duplicate guard

No real order. No `/exchange`.

### P5 — PaperEngine deeper integration

Use existing simulator only.

Pipeline:

SignalCandidate -> EdgeCalculator -> RiskEngine -> PaperIntent -> existing PaperEngine -> PaperTrade -> realized/unrealized PnL -> equity curve -> drawdown -> dashboard/export.

Requirements:

- PaperIntent only after RiskEngine
- PaperTrade labelled “not an order”
- fees/spread/slippage/latency/liquidity/copy_degradation applied
- reduce/close update PnL
- mock USDC portfolio updated
- no fake fills

### P6 — Backtest/replay from fills+deltas+books

Do not use only `closedPnl`.

Replay:

- historical fills
- reconstructed deltas
- book snapshots
- delays WS/60s/5m
- missed fills
- partial fills
- fees/spread/slippage/latency/liquidity
- stale signals
- no-trade retro
- equity/drawdown
- Sharpe/Sortino/Calmar if available
- monthly returns
- no-trade distribution
- confidence calibration

Same models as runtime and paper.

### P7 — Dashboard live and useful

Show only real data or clean empty states:

- scanner status
- source_health
- wallets scanned
- shortlist
- leader activity
- wallet rankings
- latest deltas
- signal candidates
- no_trade report
- reason code distribution
- edge_remaining
- copy_degradation details
- source failures
- market features
- volatility
- position lifecycle
- pattern detector
- paper portfolio
- paper positions from simulator only
- realized/unrealized PnL
- equity/drawdown
- risk events
- safety audit
- backtests/replays
- filters/search/sort/export
- real charts only

No placeholder trade, no demo PnL, no fake chart movement.

### P8 — Pattern detector

Analyze wallets:

- timing patterns
- per-coin stats
- win/loss distribution
- cuts losses quickly
- lets winners run
- adds to winners
- adds to losers
- overtrades
- one_big_win
- pnl_concentration
- recent vs historical
- inactive wallet
- smart/whale/suspicious/fresh labels
- risk flags
- confidence/evidence_count

Insufficient data => `INSUFFICIENT_DATA`.

### P9 — WebSocket runtime robustness

Beyond WS cap:

- heartbeat/ping
- reconnect
- exponential backoff
- subscription ack
- snapshot `isSnapshot:true`
- dedupe snapshot/update
- persistence
- fallback REST polling
- bounded duration
- source_health WS
- no infinite loops
- max 10 user-specific wallets

Tests for duplicate snapshot, reconnect, stop, fallback.

### P10 — Runtime/archive hygiene

- DB active outside `logs/`
- logs are text only
- no active SQLite in ZIP
- clean archive excludes `.git`, `data`, `logs`, `runtime`, SQLite active, pycache, caches
- SQLite backup via backup API or `VACUUM INTO`
- runtime-check detects locked DB
- archive-readiness bounded

### P11 — Multi-directory safety audit

Scan:

- code
- templates
- JS
- tools/scripts
- docs
- routes/handlers
- env files
- launchers

Detect dangerous actions, secrets, fake dashboard data, profit claims.

### P12 — Agent-safe read-only tools

Manifest tools only:

- `status.read`
- `wallet.leaderboard`
- `decision_ledger.search`
- `dashboard.export`
- `source_health.read`
- `archive.status`
- `archive.search`

No write/trade/wallet/order tools.

### P13 — Scale DEFER

Do not implement now unless runtime SQLite is stable:

- ClickHouse
- Redpanda/Kafka
- Grafana
- Prometheus
- microservices

Keep ideas only for future ingestion/analytics/monitoring separation.

---

## 10. Test suite Codex should create/strengthen

At minimum over future sprints:

- `test_decision_ledger_evidence_chain_feature_hash.py`
- `test_volatility_context_live_from_candle_snapshot.py`
- `test_position_lifecycle_hyperliquid_fields.py`
- `test_position_lifecycle_ambiguous_flip_no_trade.py`
- `test_exit_engine_follow_reduce_close.py`
- `test_exit_engine_no_matching_position_no_trade.py`
- `test_paper_engine_existing_simulation_not_replaced.py`
- `test_paper_engine_reduce_close_pnl_equity.py`
- `test_backtest_replay_from_fills_deltas_books.py`
- `test_backtest_runtime_paper_parity_reason_codes.py`
- `test_dashboard_live_no_fake_placeholders.py`
- `test_pattern_detector_insufficient_data.py`
- `test_ws_runtime_heartbeat_reconnect_dedupe.py`
- `test_clean_archive_excludes_runtime_data.py`
- `test_multi_directory_safety_audit.py`
- `test_agent_safe_manifest_readonly_only.py`
- `test_no_polymarket_runtime_or_clob.py`
- `test_no_dydx_default_runtime_import.py`
- `test_launcher_guards_match_runtime.py`

---

## 11. Commands to run

Minimum:

```bat
cd "C:\Users\flo\Desktop\Projet invest"
git status --short
git diff --stat
python -m hyper_smart_observer.app.main --safety-check
python -m hyper_smart_observer.app.main --audit-safety
```

Useful targeted tests:

```bat
python -m pytest -q tests/test_copy_run_network_read_low_liquidity_blocks_signal.py
python -m pytest -q tests/test_backtest_runtime_parity_market_features_reason_codes.py
python -m pytest -q tests/test_hypersmart_dashboard_readonly.py
python -m pytest -q tests/test_hypersmart_risk_gates.py
```

Then run new tests created by the current sprint.

If SQLite fails in sandbox/bindfs, use `/tmp` DB and document it as sandbox artifact.

---

## 12. Done definition

A sprint is done only when:

- no deletion of existing simulation/history/tests/launcher;
- Hyperliquid-only runtime preserved;
- dYdX isolated;
- Polymarket runtime absent;
- code is real, not only docs;
- tests prove behavior;
- safety/audit checks pass or failures are documented honestly;
- dashboard has no fake data;
- PaperEngine remains existing core;
- report final FR lists files, tests, commands, results, limitations, next priority.

---

## 13. Recommended next priority

If the goal is **knowing whether the bot wins or loses**, prioritize:

**P3 Position lifecycle -> P4 Exit engine -> P5 PaperEngine reduce/close PnL -> P6 backtest replay from fills/deltas/books.**

If the goal is **auditability and feature quality**, prioritize:

**P1 EvidenceChain -> P2 volatility live -> P7 dashboard.**

Best recommendation: do P3/P4/P5 first, then P1/P2 immediately after.

---

## 14. Final report format

Codex must report in French:

- git state initial;
- Browser repos checked;
- KEEP/ADAPT/BAN/DEFER changes;
- files modified;
- tests added/changed;
- commands run;
- test results;
- proof no deletion;
- proof simulation preserved;
- proof Hyperliquid-only;
- proof no Polymarket runtime;
- proof dYdX isolated;
- proof no fake data;
- limitations;
- next priority.

Mandatory final sentence:

> Hyperliquid-only runtime, simulation-only, PaperEngine preserved, no `/exchange`, no order, no signature, no private key, no Polymarket runtime, no fake data, dYdX isolated.


---

# CODEX_HYPERSMART_MASTER_PLAN_V4 — ADDENDUM SUPERSET

> Cette V4 ne supprime rien de la V3. Elle ajoute tout ce qui manquait pour que Codex puisse avancer étape par étape, point par point, en fusionnant les meilleures idées des GitHub, mais en restant strictement sur **Hyperliquid**, **simulation locale**, **read-only**, **zéro ordre réel**.

## 0. Principe central

HyperSmart n'est pas un bot de trading réel. HyperSmart est un **observateur Hyperliquid + moteur de simulation locale**.

Le but n'est pas de promettre un profit. Le but est de répondre avec preuve :

- quels wallets sont vraiment intéressants ;
- quels signaux sont rejetés et pourquoi ;
- quelles positions seraient ouvertes en paper ;
- quand elles seraient réduites/fermées ;
- combien la simulation gagne/perd ;
- avec quels frais, spread, slippage, latence, liquidité, stale signals, missed fills ;
- avec un dashboard et un ledger vérifiables.

## 1. Règles absolues à ne jamais casser

Codex doit auditer ces règles avant et après chaque sprint.

### 1.1 Autorisé

- Hyperliquid `/info` read-only.
- Hyperliquid WebSocket read-only.
- SQLite local.
- CSV/JSON exports.
- Simulation/PaperEngine existant.
- Mock USDC.
- Backtests/replays locaux.
- Dashboard read-only.
- Agent-safe read-only tools.
- Browser pour lire GitHub/docs.
- dYdX isolé/mockable/non lancé par défaut.

### 1.2 Interdit

- `/exchange`
- `Exchange` SDK opérationnel.
- ordre réel.
- cancel réel.
- modify réel.
- signature.
- private key.
- API wallet secret.
- wallet connect.
- executor-service.
- live toggle.
- Polymarket runtime.
- Kalshi runtime.
- CLOB runtime.
- ethers runtime.
- buy/sell/trade/copy/execute buttons.
- fake data.
- fake PnL.
- fake position.
- fake chart movement.
- profit promises.
- LLM in hot path.

### 1.3 Règle anti-suppression

Ne rien supprimer brutalement.

Si une partie est dangereuse ou obsolète :

1. l'isoler ;
2. la désactiver par défaut ;
3. ajouter un test ;
4. documenter `DEFER` ou `BAN`;
5. ne supprimer qu'après validation manuelle explicite.

---

## 2. Méthode Browser obligatoire avant codage

Codex doit utiliser Browser pour ouvrir tous les dépôts listés. Il ne doit pas se baser uniquement sur mémoire.

Créer ou mettre à jour :

`docs/research/HYPERSMART_GITHUB_RESCAN_CODEX_V4.md`

Pour chaque repo :

- URL.
- Fichiers lus : README/docs/src/tests/scripts si disponibles.
- Idées `KEEP`.
- Idées `ADAPT_TO_HYPERLIQUID`.
- Idées `BAN`.
- Idées `DEFER`.
- Module HyperSmart cible.
- Tests nécessaires.
- Risque sécurité/licence.
- Ce qu'il ne faut pas copier.
- Ce qui est déjà présent dans HyperSmart.
- Ce qui manque encore.

### Repos à ouvrir

- https://github.com/alsk1992/CloddsBot
- https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits
- https://github.com/MrFadiAi/Polymarket-bot
- https://github.com/lihanyu81/polymarket_lp_tool
- https://github.com/yangyuan-zhen/PolyWeather
- https://github.com/Composio-HQ/polymarket-kalshi-arbitrage-bot
- https://github.com/aarora4/Awesome-Prediction-Market-Tools
- https://github.com/NYTEMODEONLY/polyterm
- https://github.com/txbabaxyz/mlmodelpoly
- https://github.com/txbabaxyz/polyrec
- https://github.com/evan-kolberg/prediction-market-backtesting
- https://github.com/ent0n29/polybot
- https://github.com/Polymarket/agents
- https://github.com/tradingview/lightweight-charts

### Docs Hyperliquid à ouvrir

- Hyperliquid Info endpoint.
- Hyperliquid WebSocket subscriptions.
- Hyperliquid rate limits and user limits.
- Hyperliquid Python SDK uniquement pour comprendre `Info`/WS.
- Ne jamais utiliser les parties `Exchange`/order/signing.

---

## 3. Traduction des idées GitHub en modules HyperSmart

## 3.1 CloddsBot

Idées à garder :

- WebChat/dashboard local.
- Sidebar claire.
- Reports/Artifacts/Diagnostics.
- Search local.
- Historique SQLite.
- Risk engine visible.
- Backtesting.
- Trade ledger, transformé en decision/paper ledger.
- Whale tracking.
- Copy trading, transformé en simulation de suivi.
- Confidence calibration.
- SHA-256 evidence.
- Doctor CLI.
- Health panel.
- Local memory.

À adapter :

- `WebChat` -> `HyperSmart Dashboard`.
- `Trade Ledger` -> `DecisionLedger + PaperLedger`.
- `Copy Trading` -> `SignalCandidate + PaperIntent`.
- `Risk Engine` -> `DenyByDefault RiskEngine`.
- `Whale Tracking` -> `WalletIntelligence`.

À bannir :

- credentials setup trading.
- live execution.
- one command away from trading.
- DEX/EVM/Solana/DeFi actions.
- payments/token launch.
- autonomous order routing.
- API key wizard.

Modules à coder ou renforcer :

- `dashboard/`
- `decision_ledger/`
- `paper_trading/`
- `wallet_intelligence/`
- `diagnostics/`
- `source_health/`

Tests :

- dashboard loads with empty DB.
- no secret fields in UI.
- no trade/copy buttons.
- decision hash stable.
- report export references raw evidence.

## 3.2 Harrier

Idées à garder :

- One core.
- One risk layer.
- Adapter stack.
- Full dry-run.
- Copy trading as research.
- Orderbook imbalance as signal.
- Circuit breaker.
- Depth guard.
- Cooldown.
- Venue abstraction.

À adapter :

- `execution core` -> `observation/paper core`.
- `venue adapter` -> `ReadOnlyVenueAdapter`.
- `risk layer` -> single `RiskEngine`.
- `copy trading` -> `copy_simulation`.
- `market making/orderbook imbalance` -> `MarketSignalFeatures`.

À bannir :

- execution core réel.
- FAK/GTD.
- <50ms execution.
- sports execution.
- resolution sniper.
- market making réel.
- guaranteed payout.
- TP/SL réel.

Modules :

- `adapters/hyperliquid_readonly.py`
- `adapters/mock.py`
- `core/observation_core.py`
- `core/paper_core.py`
- `risk/`
- `market_signals/`

Tests :

- Hyperliquid adapter never imports Exchange.
- dYdX adapter not imported by default.
- same risk engine runtime/backtest/paper.
- orderbook imbalance becomes feature, not order.

## 3.3 MrFadi Polymarket bot

Idées à garder :

- Smart money filtering.
- Minimum winrate.
- Profit factor.
- Consistency score.
- No one-hit wonder.
- Whale/lucky-trade detection.
- Dynamic paper sizing.
- Loss halts.
- Drawdown halts.
- Risk breach alerts.
- Dashboard risk status.

À adapter HyperSmart :

- `WalletScoreV2`
- `CopyabilityScore`
- `RiskHaltState`
- `PaperSizingPolicy`
- `RiskEvent`
- `RiskDashboardPayload`

Metrics wallet :

- fills_count.
- active_days.
- realized_pnl.
- closed_pnl.
- fees.
- winrate.
- profit_factor.
- avg_win.
- avg_loss.
- max_drawdown.
- Sharpe/Sortino if valid.
- pnl_concentration.
- one_big_win_ratio.
- recency.
- consistency.
- coin concentration.
- leverage/margin risk if available.
- liquidation history.
- data_quality_score.

À bannir :

- private key.
- real funds.
- real USDC.
- real halt tied to live money.
- panic sell.
- trading buttons.

Tests :

- insufficient history rejects.
- one_big_win degrades.
- profit_factor below threshold rejects.
- data_quality low rejects.
- paper sizing reduced after mock losses.
- risk halt blocks PaperIntent.

## 3.4 polymarket_lp_tool

Idées à garder :

- WS-first.
- REST reconciliation.
- structured tracing.
- deterministic rules.
- JSON persistence.
- cooldowns.
- midpoint jump filter.
- stable confirmation.
- EMA/median smoothing.
- max chase idea -> max copy degradation.
- risk monitoring.

À adapter :

- `WS-first` -> shortlist Hyperliquid WS.
- `REST reconciliation` -> compare WS fills with userFillsByTime.
- `midpoint stability` -> `MidStabilityFilter`.
- `cooldown` -> wallet/coin/action cooldown.
- `max chase` -> `copy_degradation_bps`.

À bannir :

- OrderManager.
- apply_decision order logic.
- cancel/repost/reprice.
- post-only.
- order placement.

Modules :

- `ws_supervisor/`
- `rest_reconciler/`
- `market_signals/mid_stability.py`
- `copy_mode/cooldown.py`
- `source_health/`

Tests :

- WS missing event recovered by REST.
- duplicate snapshot ignored.
- mid jump creates NoTrade.
- cooldown blocks duplicate.
- l2Book missing no PaperIntent.

## 3.5 PolyWeather

Idées à garder :

- Realtime terminal.
- Health/status/metrics.
- authoritative dashboard snapshot.
- stale-state policy.
- event-driven updates.
- fallback refresh.
- deployment docs.
- frontend separation.
- ops diagnostics.

À adapter :

- stale source -> no paper ready.
- dashboard shows source state.
- refresh in progress -> pending, not fake.
- fallback REST if WS stale.
- source_health visible everywhere.

Modules :

- `dashboard/snapshots.py`
- `source_health/`
- `runtime_state/`
- `stale_policy.py`

Tests :

- stale signal cannot open paper trade.
- source failed dashboard shows degraded.
- refresh pending does not invent data.
- stale -> NoTradeReason.STALE_SOURCE.

## 3.6 Composio arbitrage bot

Idées à garder :

- `/health`
- `/status`
- polling loop start/stop.
- current_signal shape.
- timing gate.
- spread/edge metrics.

À adapter :

- Local scanner controls only.
- Status read-only.
- Current signal can be `NoTradeDecision`.
- Polling state visible.

À bannir :

- buy_polymarket.
- buy_polymarket_late.
- private key.
- proxy wallet.
- trade USD.
- ethers.
- CLOB.
- tradingEnabled true.

Modules :

- `api/status_readonly.py`
- `scanner/control.py`
- `scanner/run_state.py`

Tests :

- no write endpoint.
- scanner start/stop local only.
- no private key env.
- current signal never action buy.

## 3.7 Awesome Prediction Market Tools

Idées à garder :

- Analytics categories.
- Dashboards.
- Data feeds.
- Portfolio tracking.
- Alerts.
- Wallet analytics.
- Leaderboards.
- Live odds/spreads/liquidity/orderbook depth.
- Historical snapshots.
- Smart/whale/suspicious/fresh labels.
- Watchlists.

À adapter :

- Bloomberg-style dashboard for Hyperliquid wallet observation.
- Alerts disabled by default.
- Watchlist import with validation.
- Portfolio tracking = paper only.

Modules :

- `dashboard/leaderboard.py`
- `watchlists/`
- `alerts/read_only.py`
- `wallet_labels/`
- `exports/`

Tests :

- label requires evidence.
- alert disabled by default.
- watchlist validates address.
- portfolio uses paper trades only.

## 3.8 PolyTerm

Idées à garder :

- Agent-ready tooling.
- Manifest.
- JSON schemas.
- FastMCP-like read-only idea.
- Doctor diagnostics.
- llms.txt.
- llms-full.txt.
- SQLite state.
- JSON/CSV exports.
- Historical replay.
- Zero custody.
- Input sanitization.
- No bare subprocess.
- Graceful failure.
- Very high test count.

À adapter :

Créer :

- `docs/HYPERSMART_AGENT_SAFE_READONLY_MANIFEST.md`
- `docs/llms.txt`
- `docs/llms-full.txt`
- `schemas/status.read.schema.json`
- `schemas/wallet.leaderboard.schema.json`
- `schemas/wallet.detail.schema.json`
- `schemas/decision_ledger.search.schema.json`
- `schemas/dashboard.export.schema.json`
- `schemas/source_health.read.schema.json`
- `schemas/archive.status.schema.json`
- `schemas/backtest.report.schema.json`

Tools read-only :

- `status.read`
- `wallet.leaderboard`
- `wallet.detail`
- `market.features.read`
- `decision_ledger.search`
- `paper_portfolio.read`
- `backtest.report.read`
- `dashboard.export`
- `source_health.read`
- `archive.status`
- `archive.search`

À bannir :

- write tools.
- trade tools.
- wallet custody.
- shell execution.
- tools that mutate runtime except safe local scan status if explicit.

Tests :

- manifest read-only only.
- JSON schemas validate.
- malicious input sanitized.
- no subprocess.
- tool errors graceful.

## 3.9 mlmodelpoly

Idées à garder :

- WebSocket collector.
- OHLCV bars.
- CVD.
- VWAP.
- Volatility.
- Fair value model.
- Edge calculation.
- TUI dashboard.
- REST latest endpoints.
- decision_logger.
- metrics.

À adapter Hyperliquid :

`MarketSignalFeaturesV4` :

- run_id.
- coin.
- source_ts.
- local_received_ts.
- latency_ms.
- current_mid.
- mid_source.
- best_bid.
- best_ask.
- spread_bps.
- l2_bid_depth.
- l2_ask_depth.
- depth_imbalance.
- microprice.
- bbo.
- recent_trade_count.
- trade_flow_delta.
- candle_return_1m.
- candle_return_5m.
- realized_vol_bps.
- range_bps.
- atr_bps.
- vwap_estimate.
- mid_stability_score.
- liquidity_score.
- leader_delta.
- copy_degradation_bps.
- edge_remaining_bps.
- data_quality.
- source_health_ref.
- feature_hash.

À bannir :

- Binance runtime.
- TAAPI secret.
- Polymarket CLOB.
- LLM hot path.

Tests :

- missing candles degraded.
- zero division guarded.
- export exact schema.
- no fake VWAP if trades missing.

## 3.10 polyrec

Idées à garder :

- Rich CSV.
- 70+ columns.
- Terminal dashboard.
- Orderbook 5 levels.
- Spread.
- Imbalance.
- Microprice.
- Slope.
- Eat-flow.
- Returns.
- Volume.
- ATR.
- RVOL.
- Backtesting scripts.

À adapter Hyperliquid :

Créer `scan_features` riche :

- run_id.
- timestamp.
- wallet.
- coin.
- leader_delta.
- lifecycle_event.
- current_mid.
- mid_source.
- l2_level_1..N.
- spread_bps.
- depth_imbalance.
- microprice.
- depth_slope.
- recent_trade_flow.
- realized_vol_bps.
- range_bps.
- atr_bps.
- liquidity_score.
- copy_degradation_bps.
- edge_remaining_bps.
- data_quality.
- source_health.
- feature_hash.
- decision_id.
- no_trade_reason.

À bannir :

- Chainlink/Binance dependencies.
- Polymarket orderbook runtime.
- logs as primary DB.
- external subprocess fragility.

Tests :

- CSV and JSON same rows.
- schema pinned.
- decision row joins feature_hash.
- no bare subprocess.

## 3.11 prediction-market-backtesting

Idées à garder :

- Custom adapters.
- Staged loading.
- Materialized caches.
- Unified cache/local/archive/API bus idea.
- Book replay deltas.
- Trade ticks.
- Multi-run reports.
- Equity chart.
- PnL ticks.
- Drawdown.
- Sharpe.
- Monthly returns.
- Backtest/runtime parity.

À adapter Hyperliquid :

Modules :

- `backtest/runtime_parity.py`
- `backtest/historical_fill_replay.py`
- `backtest/orderbook_replay.py`
- `backtest/scenarios.py`
- `backtest/report.py`
- `backtest/cache.py`

Scénarios :

- follow opens only.
- follow opens+reduce+close.
- delayed follow 5s.
- delayed follow 60s.
- delayed follow 5m.
- top 1 wallet.
- top N wallets.
- coin allowlist.
- score threshold strict/loose.
- high volatility.
- low liquidity.
- stale source.
- missed fill.
- partial close.
- leader flip.
- WS outage.
- REST-only fallback.

Metrics :

- mock total return.
- realized_pnl.
- unrealized_pnl.
- fees.
- spread cost.
- slippage cost.
- latency cost.
- missed_fill_count.
- no_trade distribution.
- winrate.
- profit factor.
- max drawdown.
- Sharpe/Sortino if valid.
- monthly returns.
- avg duration.
- MAE/MFE.
- confidence calibration.

À bannir :

- copying mixed-license code.
- live sandbox plumbing.
- execution path.

Tests :

- same reason code runtime/backtest.
- same PaperEngine model.
- replay deterministic.
- no network unless explicitly read-only mock.

## 3.12 polybot

Idées à garder uniquement en DEFER :

- Service separation.
- Ingestion.
- Strategy runtime.
- Analytics.
- Monitoring.
- ClickHouse.
- Redpanda.
- Grafana.
- Prometheus.
- Research snapshots.
- Replication scoring.
- Strategy analysis dashboard.

À ne pas faire maintenant :

- microservices.
- executor-service.
- live mode.
- market making.
- Java stack.
- ClickHouse migration.
- Redpanda pipeline.
- Grafana deployment.

Adaptation court terme :

- garder architecture SQLite monolith local.
- créer interfaces qui pourraient évoluer plus tard :
  - `ingestion`.
  - `strategy_research`.
  - `analytics`.
  - `monitoring`.
- pas de scale tant que runtime local pas parfait.

Tests :

- no executor-service.
- no live profile.
- no ClickHouse required.
- local SQLite path only.

## 3.13 Polymarket/agents

Idées à garder :

- typed connectors.
- Pydantic schemas.
- evidence reports.
- RAG/research summaries.
- offline strategy explanation.
- agent task decomposition.

À adapter :

- `research_connector` offline only.
- `evidence_report_builder`.
- `decision_explainer`.
- `wallet_thesis_report`.

À bannir :

- Polymarket trading.
- CLOB.
- private keys.
- signing.
- autonomous agent placing bets.
- any write/trade action.

Tests :

- no polymarket package runtime.
- no CLOB import.
- no trade action strings.
- explanation uses existing evidence only.

## 3.14 Lightweight Charts

Idées à garder :

- charts fluides.
- equity curve.
- PnL curve.
- drawdown curve.
- spread/liquidity chart.
- source latency chart.
- edge remaining chart.
- paper positions markers.
- leader fill markers.
- no_trade markers.
- zoom/pan.
- crosshair.

À adapter :

- charts read from real DB/export only.
- no synthetic movement.
- if no data -> empty state.
- if stale -> stale badge.

Tests :

- no fake chart points.
- empty DB empty chart.
- chart data equals paper ledger.
- stale source badge visible.

---

## 4. Hyperliquid data contract à coder précisément

## 4.1 Endpoints read-only requis

Adapter Hyperliquid doit exposer au minimum :

- `allMids`
- `l2Book`
- `candleSnapshot`
- `recentTrades` si utile et rate-budget OK
- `clearinghouseState`
- `userFills`
- `userFillsByTime`
- `openOrders`
- `frontendOpenOrders`
- `orderStatus` uniquement diagnostic
- `userFees` si utile
- `exchangeStatus` si utile

Chaque appel doit retourner :

- data normalized.
- raw_ref/hash.
- source_endpoint.
- source_ts if available.
- local_received_ts.
- latency_ms.
- data_quality.
- source_health update.
- rate_weight estimate.
- truncated/window metadata when relevant.

## 4.2 Pagination

Règle officielle : réponses time-range `/info` = 500 éléments/blocs max.

Codex doit implémenter :

- pagination via last timestamp.
- max_pages.
- max_items.
- bounded runtime.
- stopped_reason.
- window_complete boolean.
- oldest_available_ts.
- truncated boolean.

## 4.3 userFills/userFillsByTime metadata

Pour chaque backfill :

- wallet.
- start_time.
- end_time.
- aggregate_by_time.
- response_count.
- max_response_count.
- truncated.
- window_complete.
- oldest_available_ts.
- stopped_reason.
- rate_weight.

## 4.4 allMids / mid_source

`MarketMid` doit porter :

- `current_mid`
- `mid_source`
- `MID_FROM_BOOK`
- `MID_FROM_LAST_TRADE_FALLBACK`
- `MID_MISSING`
- `data_quality`
- `is_stale`
- `source_health_ref`

Si fallback last trade ou missing : prudence.

## 4.5 l2Book

`OrderBookSnapshot` :

- max 20 levels per side.
- best_bid.
- best_ask.
- spread_bps.
- total_bid_depth_N.
- total_ask_depth_N.
- depth_imbalance.
- microprice.
- depth_slope.
- liquidity_score.
- source_ts.
- local_received_ts.
- latency_ms.
- data_quality.

Règle : l2Book insuffisant ou stale => NoTrade si edge non mesurable.

## 4.6 candleSnapshot/trades

`VolatilityContext` :

- coin.
- window.
- candle_count.
- trade_count if trades.
- realized_vol_bps.
- range_bps.
- atr_bps.
- rvol if reliable.
- bucket.
- source_health_ref.
- data_quality.
- degraded_reason.

Si indisponible : `None` + degraded. Ne jamais inventer.

## 4.7 WebSocket subscriptions

WS shortlist seulement.

Subscriptions utiles :

- allMids.
- l2Book.
- trades.
- candle.
- userFills.
- clearinghouseState.
- openOrders optionally as context only.
- bbo if available.

WS supervisor :

- max 10 user-specific wallets.
- max subscriptions budget.
- heartbeat/ping.
- reconnect.
- exponential backoff.
- subscription ack.
- snapshot `isSnapshot:true`.
- update `isSnapshot:false`.
- dedupe.
- persistence.
- REST reconcile.
- bounded duration.
- graceful shutdown.
- source_health.

Règle : openOrders alone = context only, never PaperIntent.

---

## 5. Common Data Model V4

Tous les objets doivent contenir :

- `schema_version`
- `adapter_version`
- `venue`
- `source_endpoint_or_channel`
- `source_ts`
- `local_received_ts`
- `latency_ms`
- `raw_ref`
- `raw_hash`
- `data_quality`
- `is_stale`

Objets requis :

- `CollectionRun`
- `SourceHealth`
- `RateBudgetSnapshot`
- `NormalizedFill`
- `NormalizedPosition`
- `NormalizedOpenOrder`
- `MarketMid`
- `OrderBookSnapshot`
- `VolatilityContext`
- `MarketSignalFeatures`
- `WalletSnapshot`
- `WalletScoreV2`
- `CopyabilityScore`
- `PositionLifecycleEvent`
- `LeaderDelta`
- `SignalCandidate`
- `EdgeEstimate`
- `RiskDecision`
- `NoTradeDecision`
- `PaperIntent`
- `PaperTrade`
- `PaperPosition`
- `PaperPortfolioSnapshot`
- `DecisionLedgerEntry`
- `EvidenceChain`
- `BacktestRun`
- `BacktestEvent`
- `BacktestReport`
- `DashboardPayload`
- `DashboardEvent`
- `RiskEvent`
- `AgentSafeToolManifest`

---

## 6. Architecture cible étape par étape

## Étape 1 — Audit actuel

Codex doit commencer par repérer :

- modules Hyperliquid existants.
- copy_loop.
- scanner.
- DB schema.
- PaperTradingSimulator.
- RiskEngine.
- EdgeCalculator.
- Dashboard exporter.
- Backtest/replay.
- tests.
- dYdX imports.
- Polymarket imports.
- launchers.
- safety/audit scripts.

Sortie attendue :

`docs/research/HYPERSMART_CURRENT_CODE_AUDIT_V4.md`

Avec :

- ce qui existe.
- ce qui est partiel.
- ce qui manque.
- fichiers concernés.
- risques.
- prochain sprint recommandé.

## Étape 2 — EvidenceLedger

Coder :

- table ou modèle `decision_ledger`.
- table ou modèle `evidence_chain`.
- FK/logical ref decision -> feature_hash.
- refs fills/positions/orderbook/mid/candles/source_health.
- hash stable.
- export JSON/CSV.
- search read-only.

Tests :

- decision retrouve feature row.
- no_trade retrouve evidence.
- paper_intent retrouve evidence.
- hash stable.
- missing evidence -> fail/NoTrade.

## Étape 3 — Volatility live

Coder :

- `info_client.get_candle_snapshot`.
- optional `get_recent_trades`.
- normalizer candles/trades.
- `compute_volatility_context`.
- brancher dans `market_features_by_coin`.
- dashboard/export.
- source_health.

Tests :

- candles valid.
- candles empty.
- trades fallback.
- rate budget.
- no fake.

## Étape 4 — Position lifecycle

Coder :

- `position_lifecycle/reconstructor.py`
- parse Hyperliquid fill fields.
- reconstruct open/add/reduce/close/flip.
- partial fill handling.
- partial close handling.
- leader episode ids.
- confidence.
- ambiguous -> NoTrade.

Tests :

- long open.
- short open.
- add.
- reduce.
- close.
- flip.
- partial.
- closedPnl mapping.
- fee mapping.
- ambiguous no trade.

## Étape 5 — Exit engine paper

Coder :

- `paper_trading/exit_engine.py`
- follow leader reduce.
- follow leader close.
- partial close.
- time stop.
- trailing stop.
- max MAE/MFE.
- max holding.
- max positions.
- blocked assets.
- duplicate close guard.
- no matching paper position -> NoTrade.

Tests :

- leader close closes paper.
- leader reduce partially closes.
- no matching no trade.
- time stop.
- trailing stop.
- duplicate blocked.
- PnL realized.

## Étape 6 — PaperEngine fidelity

Renforcer existant, pas nouveau moteur.

Coder/valider :

- entry/exit cost model.
- fees.
- spread.
- slippage.
- latency.
- liquidity.
- copy degradation.
- missed fill.
- mark-to-market latent PnL.
- realized PnL.
- equity curve.
- drawdown.
- paper USDC portfolio.
- paper positions.
- paper trade ledger.

Tests :

- PaperIntent after RiskEngine only.
- PaperTrade not an order.
- realized PnL after close.
- unrealized PnL with real mid.
- drawdown.
- cost breakdown.
- no mid -> no fake latent PnL.

## Étape 7 — Backtest/replay

Coder :

- replay fills/deltas/books.
- event queue.
- delays scenarios.
- same models runtime.
- historical source_health.
- backtest report.

Tests :

- runtime/backtest parity.
- same reason codes.
- deterministic run.
- delayed copy changes result.
- missed fill counted.
- partial close.
- low liquidity.
- stale source.

## Étape 8 — Wallet intelligence and pattern detector

Coder :

- WalletScoreV2.
- CopyabilityScore.
- pattern detector.
- labels.
- confidence.
- evidence_count.
- insufficient data state.

Patterns :

- timing.
- per coin edge.
- win/loss distribution.
- cuts losses quickly.
- lets winners run.
- adds winners.
- adds losers.
- overtrades.
- one big win.
- pnl concentration.
- recent vs historical.
- inactive wallet.
- suspicious wallet.
- fresh wallet.
- whale.

Tests :

- insufficient data.
- one big win.
- overconcentration.
- inactive.
- high confidence only with enough evidence.
- labels visible in dashboard.

## Étape 9 — Dashboard réel

Coder :

- source health panel.
- wallet leaderboard.
- latest deltas.
- lifecycle panel.
- candidates.
- no trade report.
- edge/copy degradation.
- volatility.
- paper portfolio.
- paper positions.
- PnL/equity/drawdown.
- risk events.
- backtests.
- decision ledger search.
- exports.
- real charts.

Tests :

- empty DB no fake.
- real DB shows actual values.
- chart data equals ledger.
- stale badge.
- no trade buttons.

## Étape 10 — WS robustness

Coder :

- supervisor.
- heartbeat.
- reconnect/backoff.
- ack handling.
- snapshot/update dedupe.
- bounded duration.
- REST fallback.
- persistence.
- source_health.

Tests :

- reconnect.
- duplicate ignored.
- missed event reconciled.
- max 10 wallets.
- graceful shutdown.

## Étape 11 — Runtime/archive hygiene

Coder :

- runtime DB path outside logs.
- logs text only.
- archive clean.
- sqlite backup.
- locked DB detection.
- audit bounded scan.
- `.git`, data, logs, runtime, sqlite, pycache excluded.

Tests :

- clean archive excludes forbidden.
- DB backup works.
- locked DB detected.
- audit doesn't scan huge runtime.

## Étape 12 — Security audit multi-dossiers

Scanner :

- `hyper_smart_observer/`
- `src/hl_observer/`
- templates.
- JS.
- tools.
- scripts.
- docs.
- routes.
- handlers.
- launchers.
- env examples.

Tests/audit rules :

- no `/exchange`.
- no Exchange SDK operational.
- no signature.
- no private key.
- no wallet connect.
- no trade buttons.
- no Polymarket runtime.
- no CLOB.
- no fake data markers.
- no profit claims.

## Étape 13 — Agent-safe read-only

Coder docs/schemas/tools read-only.

Tests :

- manifest read-only only.
- schemas valid.
- no write/trade.
- input sanitized.
- graceful failure.

---

## 7. Definition of Done globale

Un sprint est terminé seulement si :

- aucune suppression brutale.
- safety-check OK.
- audit-safety OK.
- tests nouveaux OK.
- tests ciblés existants OK.
- rapport FR clair.
- dashboard/export sans fake.
- PaperEngine préservé.
- dYdX isolé.
- Polymarket runtime absent.
- `/exchange` absent.
- décision ou NoTrade traçable dans evidence chain.
- PnL paper calculé depuis données réelles ou explicitement absent.
- source_health visible.

---

## 8. Ordre recommandé des prochains sprints

### Sprint 1 recommandé : position_lifecycle + exit_engine + PaperEngine exits

Pourquoi :

- c'est le plus important pour savoir si le bot gagne/perd.
- ouvrir sans bien fermer ne suffit pas.
- closedPnl leader ne suffit pas.
- réduire/fermer/flip/partial est vital.

Livrables :

- lifecycle events.
- exit engine.
- paper reduce/close.
- PnL realized.
- tests.
- dashboard minimal.

### Sprint 2 : evidence_chain SQL + feature refs

Pourquoi :

- toute décision doit être auditable.

### Sprint 3 : candleSnapshot/trades -> volatility live

Pourquoi :

- meilleur edge/risk/context.

### Sprint 4 : backtest/replay fills+deltas+books

Pourquoi :

- valider stratégie sur historique.

### Sprint 5 : dashboard V2 vivant

Pourquoi :

- rendre tout visible et utilisable.

### Sprint 6 : WS supervisor robuste

Pourquoi :

- rendre le runtime fiable.

### Sprint 7 : agent-safe manifest et archive hygiene

Pourquoi :

- rendre Codex/Jules/agents sûrs.

---

## 9. Objectif court à coller dans Codex après avoir placé ce fichier

```text
Lis docs/CODEX_HYPERSMART_MASTER_PLAN_V4.md et AGENTS.md si présent. Utilise Browser pour revérifier tous les GitHub et docs Hyperliquid listés. Travaille local only dans C:\Users\flo\Desktop\Projet invest. Ne supprime rien. Hyperliquid-only, simulation locale only. Applique uniquement la prochaine priorité non terminée du plan, en commençant par position_lifecycle+exit_engine+PaperEngine exits si non fait. Code réel, tests, safety-check, audit-safety, rapport final FR.
```


---

# CODEX_HYPERSMART_MASTER_PLAN_V5 — AUTONOMOUS CODING SPEC

> Cette V5 est un **superset**. Ne rien enlever à la V4. Elle ajoute des tickets ultra précis pour un agent de codage autonome.  
> Objectif absolu : transformer HyperSmart en observateur Hyperliquid + simulateur local vérifiable, capable de prouver si la stratégie gagne ou perd en paper, sans jamais trader réellement.

---

## A. Mission de Codex

Codex doit travailler comme un ingénieur autonome mais prudent :

1. Lire ce fichier en entier.
2. Lire `AGENTS.md` si présent.
3. Auditer le repo local avant toute modification.
4. Utiliser Browser pour revérifier tous les GitHub et docs Hyperliquid listés.
5. Créer un rapport de recherche local.
6. Choisir une seule priorité verticale à la fois.
7. Coder seulement du read-only/simulation locale.
8. Ajouter ou renforcer les tests.
9. Lancer les contrôles sécurité.
10. Produire un rapport final français, clair, honnête.

Codex ne doit jamais faire de refactor décoratif ou de grande réécriture sans preuve.

---

## B. Sources externes à relire à chaque grand sprint

Créer ou mettre à jour :

`docs/research/HYPERSMART_GITHUB_RESCAN_CODEX_V5.md`

Format obligatoire pour chaque repo :

```md
## Repo: <url>
### Ce que j'ai ouvert
- README:
- docs:
- src:
- tests:
- scripts:
- configs:

### Idées gardées
### Idées adaptées à Hyperliquid
### Idées bannies
### Idées différées
### Modules HyperSmart impactés
### Tests à créer
### Risques sécurité/licence
### Ce que je ne copierai pas
### Ce qui manque encore dans HyperSmart
```

Repos à revérifier :

- `https://github.com/alsk1992/CloddsBot`
- `https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits`
- `https://github.com/MrFadiAi/Polymarket-bot`
- `https://github.com/lihanyu81/polymarket_lp_tool`
- `https://github.com/yangyuan-zhen/PolyWeather`
- `https://github.com/Composio-HQ/polymarket-kalshi-arbitrage-bot`
- `https://github.com/aarora4/Awesome-Prediction-Market-Tools`
- `https://github.com/NYTEMODEONLY/polyterm`
- `https://github.com/txbabaxyz/mlmodelpoly`
- `https://github.com/txbabaxyz/polyrec`
- `https://github.com/evan-kolberg/prediction-market-backtesting`
- `https://github.com/ent0n29/polybot`
- `https://github.com/Polymarket/agents`
- `https://github.com/tradingview/lightweight-charts`

Docs Hyperliquid :

- Info endpoint.
- WebSocket subscriptions.
- Rate limits and user limits.
- SDK Python uniquement pour `Info`/WS.
- Ne jamais importer/activer `Exchange`.

---

## C. Sécurité non négociable

### C.1 Interdits globaux

Codex doit scanner tout le repo pour :

- `/exchange`
- `Exchange(`
- `exchange.order`
- `place_order`
- `cancel_order`
- `modify_order`
- `signature`
- `sign`
- `nonce`
- `private_key`
- `secret_key`
- `wallet`
- `connect wallet`
- `buy`
- `sell`
- `execute`
- `trade`
- `copy now`
- `polymarket`
- `clob`
- `ethers`
- `kalshi`
- `real USDC`
- `mainnet execution`
- `profit guaranteed`

Attention : certains mots peuvent être autorisés dans docs/tests/audits s'ils sont explicitement marqués BAN.  
Mais ils ne doivent pas être dans un chemin runtime actif.

### C.2 Commandes sécurité minimales

Codex doit exécuter si disponibles :

```bat
python -m hyper_smart_observer.app.main --safety-check
python -m hyper_smart_observer.app.main --audit-safety
python -m pytest -q tests
```

Si la suite entière est trop longue, lancer au minimum :

```bat
python -m pytest -q tests/test_hypersmart_risk_gates.py
python -m pytest -q tests/test_hypersmart_dashboard_readonly.py
python -m pytest -q tests/test_no_exchange_sdk_imports_or_actions.py
python -m pytest -q tests/test_no_polymarket_clob_or_private_key_imports.py
python -m pytest -q tests/test_backtest_runtime_parity_market_features_reason_codes.py
```

---

## D. Architecture cible complète

```text
Hyperliquid /info + WS read-only
        |
        v
HyperliquidAdapter
        |
        v
CollectionRun + SourceHealth + RawRefs + RateBudget
        |
        v
NormalizedFill / Position / OpenOrder / MarketMid / L2Book / Candles
        |
        v
PositionLifecycle + MarketSignalFeatures + VolatilityContext
        |
        v
WalletScoreV2 + CopyabilityScore + PatternDetector
        |
        v
LeaderDelta -> SignalCandidate -> EdgeEstimate
        |
        v
RiskEngine deny-by-default
        |
        +--> NoTradeDecision -> DecisionLedger -> Dashboard
        |
        +--> PaperIntent -> PaperEngine -> PaperTrade/PaperPosition/PnL -> Dashboard
        |
        v
Backtest/Replay uses same models and same risk logic
```

Aucun module ne doit contourner cette chaîne.

---

## E. Tickets détaillés à implémenter

---

# TICKET 01 — Audit réel du repo avant codage

## But

Savoir exactement ce qui existe, ce qui est partiel, ce qui manque.

## À faire

Créer :

`docs/research/HYPERSMART_CURRENT_CODE_AUDIT_V5.md`

Inclure :

- arborescence utile ;
- modules Hyperliquid ;
- modules dYdX ;
- modules Polymarket éventuels ;
- PaperEngine ;
- RiskEngine ;
- EdgeCalculator ;
- Dashboard ;
- Backtest ;
- SQLite schema ;
- launchers ;
- tests ;
- scripts audit ;
- docs.

## Sortie attendue

Table :

```md
| Domaine | Existe | Partiel | Manque | Fichiers | Risque | Prochaine action |
```

## Tests

Pas forcément de test code, mais le rapport doit être créé.

## Done

Codex sait quelle priorité appliquer sans deviner.

---

# TICKET 02 — HyperliquidAdapter read-only strict

## But

Avoir un adapter propre, borné, traçable.

## À coder

Fichiers possibles :

- `hyper_smart_observer/adapters/hyperliquid_readonly.py`
- `hyper_smart_observer/hyperliquid/info_client.py`
- `hyper_smart_observer/source_health/models.py`
- `hyper_smart_observer/rate_limits/hyperliquid.py`

Méthodes read-only :

```python
get_all_mids()
get_l2_book(coin)
get_candle_snapshot(coin, interval, start_time=None, end_time=None)
get_recent_trades(coin)
get_user_fills(wallet)
get_user_fills_by_time(wallet, start_time, end_time, aggregate_by_time=True)
get_clearinghouse_state(wallet)
get_open_orders(wallet)
get_frontend_open_orders(wallet)
get_user_fees(wallet)
get_exchange_status()
```

Chaque méthode doit retourner :

- `data`
- `source_endpoint`
- `source_ts`
- `local_received_ts`
- `latency_ms`
- `raw_ref`
- `raw_hash`
- `data_quality`
- `source_health_ref`
- `rate_weight`
- `stopped_reason` si pagination.

## Interdit

- `post /exchange`
- signature
- nonce
- action payload
- order/cancel/modify

## Tests

- adapter has no Exchange import.
- `/exchange` string absent du runtime.
- missing response => degraded, not crash.
- l2Book missing => no PaperIntent.
- pagination bounded.
- rate weight computed.

---

# TICKET 03 — SourceHealth global

## But

Ne jamais prendre une décision sans savoir si la donnée est fraîche et fiable.

## Modèle

`SourceHealth` :

```python
source_id: str
venue: str
endpoint_or_channel: str
status: OK|DEGRADED|FAIL|STALE|RATE_LIMITED
source_ts: int|None
local_received_ts: int
latency_ms: float|None
staleness_ms: int|None
retry_count: int
rate_weight: int|None
rate_budget_remaining: int|None
degraded_reason: str|None
raw_ref: str|None
raw_hash: str|None
```

## À brancher

- allMids.
- l2Book.
- candleSnapshot.
- trades.
- userFills.
- userFillsByTime.
- clearinghouseState.
- openOrders.
- WS userFills.
- WS l2Book.
- WS allMids.
- dashboard.
- DecisionLedger.
- exports.

## Tests

- stale source blocks PaperIntent.
- degraded source visible dashboard.
- source_health row exported.
- rate limited => scanner slows/stops.

---

# TICKET 04 — Common Data Model complet

## But

Tous les modules doivent parler le même langage.

## Objets à créer/valider

- `CollectionRun`
- `RateBudgetSnapshot`
- `SourceHealth`
- `NormalizedFill`
- `NormalizedPosition`
- `NormalizedOpenOrder`
- `MarketMid`
- `OrderBookSnapshot`
- `VolatilityContext`
- `MarketSignalFeatures`
- `WalletSnapshot`
- `WalletScoreV2`
- `CopyabilityScore`
- `PositionLifecycleEvent`
- `LeaderDelta`
- `SignalCandidate`
- `EdgeEstimate`
- `RiskDecision`
- `NoTradeDecision`
- `PaperIntent`
- `PaperTrade`
- `PaperPosition`
- `PaperPortfolioSnapshot`
- `DecisionLedgerEntry`
- `EvidenceChain`
- `BacktestRun`
- `BacktestEvent`
- `BacktestReport`
- `DashboardPayload`
- `RiskEvent`
- `AgentSafeToolManifest`

## Champs obligatoires presque partout

```python
schema_version
adapter_version
venue
source_endpoint_or_channel
source_ts
local_received_ts
latency_ms
raw_ref
raw_hash
data_quality
is_stale
```

## Tests

- model required metadata.
- no object accepted without venue/source/data_quality.
- serialization JSON stable.
- schema version pinned.

---

# TICKET 05 — MarketSignalFeatures V5

## But

Transformer allMids/l2Book/candles/trades en features fiables.

## Champs

```text
run_id
coin
source_ts
local_received_ts
latency_ms
current_mid
mid_source
best_bid
best_ask
spread_bps
l2_levels_count
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
buy_sell_pressure
trade_flow_delta
candle_return_1m
candle_return_5m
realized_vol_bps
range_bps
atr_bps
volatility_bucket
mid_stability_score
liquidity_score
leader_delta_side
leader_delta_size
leader_reference_price
copy_degradation_bps
edge_remaining_bps
data_quality
source_health_ref
feature_hash
```

## Calculs

- `spread_bps = (ask-bid)/mid*10000`
- `microprice = weighted bid/ask by opposite depth`
- `depth_imbalance = (bid_depth-ask_depth)/(bid_depth+ask_depth)`
- `copy_degradation_bps = abs(current_mid - leader_ref)/leader_ref*10000`
- `liquidity_score` borné 0..1
- division par zéro toujours protégée.

## No fake

Si trades absents :

- trade_count=None
- buy_sell_pressure=None
- data_quality=DEGRADED

Si candles absentes :

- volatility_context=None
- no invented ATR.

## Tests

- exact CSV schema.
- zero division safe.
- l2Book missing degraded.
- spread too wide no trade.
- low liquidity no trade.
- feature_hash stable.

---

# TICKET 06 — Volatility live

## But

Brancher enfin `candleSnapshot`/trades dans le runtime.

## À coder

- `get_candle_snapshot`.
- normalizer candles.
- `compute_volatility_context`.
- brancher dans `_market_features_by_coin`.
- exporter.
- dashboard.

## Métriques

- realized_vol_bps.
- high_low_range_bps.
- atr_bps.
- volatility_bucket.
- candle_count.
- window.
- source_health_ref.

## Règles

- données absentes -> None/degraded.
- données stale -> NoTrade possible.
- volatilité extrême -> risk flag ou edge penalty.
- jamais de valeur synthétique.

## Tests

- candles valid.
- candles empty.
- malformed candles.
- stale candles.
- extreme volatility.
- dashboard displays real bucket.

---

# TICKET 07 — PositionLifecycle Hyperliquid

## But

Comprendre ce que le leader a réellement fait.

## Inputs

Champs Hyperliquid fills :

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
crossed
fee
tid
liquidation
feeToken
builderFee
```

## Events à produire

```text
OPEN_LONG
OPEN_SHORT
ADD_LONG
ADD_SHORT
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

## Logique

- `startPosition` aide à comprendre avant/après.
- `dir` est plus fiable que `side` seul.
- `closedPnl` aide à détecter close/reduce.
- plusieurs fills même `oid`/temps peuvent former un seul event.
- partial fill doit être agrégé.
- flip doit produire close ancien + open nouveau si possible.
- ambigu -> UNKNOWN + NoTrade.

## Champs event

```text
event_id
wallet
coin
event_type
event_time
source_fill_hashes
avg_px
total_sz
start_position
end_position_estimate
closed_pnl
fees
confidence
reasoning
```

## Tests

- open long.
- open short.
- add.
- reduce.
- close.
- flip.
- partial fill.
- liquidation.
- ambiguous no trade.
- fee included.

---

# TICKET 08 — LeaderDelta

## But

Transformer lifecycle en signal potentiel.

## LeaderDelta

```text
delta_id
wallet
coin
lifecycle_event_id
action OPEN|ADD|REDUCE|CLOSE|FLIP|IGNORE
side LONG|SHORT|NONE
size
reference_price
leader_time
observed_time
latency_ms
confidence
evidence_refs
```

## Règles

- open/add peut créer SignalCandidate.
- reduce/close doit aller à ExitEngine si paper position existe.
- openOrders seuls ne créent jamais delta actionable.
- stale delta -> NoTrade.
- low confidence -> NoTrade.
- duplicate delta -> ignored.

## Tests

- fill open -> candidate.
- fill close -> exit request.
- openOrders only -> context only.
- stale -> no trade.
- duplicate -> ignored.

---

# TICKET 09 — EdgeEstimate

## But

Savoir si copier a encore un edge après coûts.

## Inputs

- leader_reference_price.
- current_mid.
- spread_bps.
- fees_bps.
- slippage_bps.
- latency_penalty_bps.
- copy_degradation_bps.
- liquidity_score.
- volatility_penalty_bps.
- risk_buffer_bps.

## Output

```text
gross_edge_bps
costs_bps
edge_remaining_bps
edge_quality
unmeasurable_reason
```

## Règles

- si current_mid missing -> EDGE_UNMEASURABLE.
- si leader price missing -> EDGE_UNMEASURABLE.
- si spread missing -> EDGE_UNMEASURABLE.
- edge_remaining < min -> NoTrade.
- low liquidity -> NoTrade.
- high volatility can reduce edge.

## Tests

- edge ok.
- edge too low.
- missing mid.
- missing leader price.
- spread too wide.
- liquidity too low.
- volatility penalty.

---

# TICKET 10 — RiskEngine deny-by-default

## But

Aucun PaperIntent sans validation explicite.

## Gates

- safety mode simulation.
- source freshness.
- wallet score.
- copyability score.
- lifecycle confidence.
- edge measurable.
- edge minimum.
- liquidity minimum.
- spread maximum.
- volatility allowed.
- max copy degradation.
- max open positions.
- coin allowlist/blocklist.
- notional cap.
- drawdown halt.
- loss streak halt.
- daily paper loss cap.
- duplicate guard.
- cooldown.
- stale signal.
- no matching paper position for exit.

## Output

- `ALLOW_PAPER_INTENT`
- `DENY_NO_TRADE`
- reasons list.
- evidence refs.

## Tests

- each gate denies.
- deny by default.
- multiple reasons preserved.
- allow only with all gates.

---

# TICKET 11 — PaperEngine fidelity

## But

La simulation doit être crédible.

## Entrée

`PaperIntent`

## Actions paper

- open position.
- add.
- reduce.
- close.
- expire stale intent.
- reject missed fill.
- mark-to-market.

## Coûts

- taker/maker fee estimate.
- spread cost.
- slippage.
- latency.
- liquidity.
- copy degradation.
- funding if available later.
- fee token.

## Portfolio

- starting_equity.
- cash_mock_usdc.
- open_notional.
- used_margin_mock.
- realized_pnl.
- unrealized_pnl.
- total_equity.
- max_drawdown.
- exposure_by_coin.
- exposure_by_wallet.
- trade_count.
- winrate.
- fees_paid.

## Règles

- pas de moteur parallèle.
- utiliser PaperTradingSimulator existant.
- PaperTrade doit dire `not_an_order=True`.
- pas de PnL latent sans mid réel.
- pas de position fake.

## Tests

- open.
- add.
- reduce.
- close.
- fees.
- slippage.
- realized.
- unrealized with mid.
- no mid no fake.
- drawdown.
- exposure cap.

---

# TICKET 12 — ExitEngine paper

## But

Ne pas seulement ouvrir. Savoir sortir.

## Sources d'exit

- leader reduce.
- leader close.
- leader flip.
- time stop.
- trailing stop.
- max MAE.
- max MFE take profit simulation.
- max holding time.
- stale source.
- risk halt.
- manual local paper stop if implemented read-only/config only.

## Output

- `PaperExitIntent`
- `NoTradeDecision` if invalid.
- `PaperTrade` reduce/close if allowed.

## Règles

- no matching paper position -> NoTrade.
- duplicate close -> ignored.
- partial close respects size.
- close cannot exceed open size.
- exit uses same cost model.
- leader close confidence required.

## Tests

- leader close.
- leader reduce.
- leader flip.
- trailing stop.
- time stop.
- max MAE.
- duplicate.
- no matching.
- realized PnL.

---

# TICKET 13 — Backtest/replay sérieux

## But

Tester la stratégie sur historique sans triche.

## Events

- historical fills.
- reconstructed lifecycle events.
- market features snapshots.
- orderbook snapshots.
- candles.
- simulated delays.
- risk decisions.
- paper actions.

## Scénarios

- instant observed.
- 5s delay.
- 60s delay.
- 5m delay.
- REST-only.
- WS outage.
- low liquidity.
- high spread.
- high volatility.
- top 1 wallet.
- top 10 wallets.
- strict score.
- loose score.
- opens only.
- opens+exits.
- no adds.
- allow adds.
- close follow on.
- close follow off.

## Metrics

- total return.
- realized_pnl.
- unrealized_pnl.
- max_drawdown.
- Sharpe.
- Sortino.
- Calmar.
- winrate.
- profit_factor.
- avg_win.
- avg_loss.
- fees.
- slippage.
- spread cost.
- latency cost.
- missed fills.
- no_trade distribution.
- time in position.
- MAE.
- MFE.
- monthly returns.
- confidence calibration.

## Tests

- deterministic replay.
- parity with runtime.
- no network.
- no fake orderbook.
- no lookahead.
- delayed scenario worse/better measured.
- report JSON schema.

---

# TICKET 14 — WalletIntelligence V2

## But

Choisir les bons leaders, pas juste les plus gros PnL.

## Features wallet

- total_fills.
- active_days.
- recent_activity.
- realized_pnl.
- closed_pnl.
- unrealized if available.
- fees.
- winrate.
- profit_factor.
- avg_win/loss.
- max_drawdown.
- Sharpe/Sortino.
- consistency.
- pnl_concentration.
- one_big_win_ratio.
- coin_concentration.
- leverage risk.
- liquidation_count.
- avg_holding_time.
- cuts_losses_score.
- lets_winners_run_score.
- add_to_winner_score.
- add_to_loser_penalty.
- overtrade_score.
- recency_score.
- data_quality_score.

## Labels

- SMART
- WHALE
- SUSPICIOUS
- FRESH
- INACTIVE
- ONE_HIT_WONDER
- OVERCONCENTRATED
- HIGH_DRAWDOWN
- LOW_EVIDENCE
- WATCHLIST

## Output

- `WalletScoreV2`
- `CopyabilityScore`
- `RiskFlags`
- evidence refs.

## Tests

- insufficient data.
- one big win.
- high drawdown.
- high consistency.
- inactive.
- suspicious.
- label explanations.

---

# TICKET 15 — PatternDetector

## But

Trouver les comportements copiables.

## Patterns

- entry timing.
- exit timing.
- per coin specialization.
- session/time-of-day edge.
- volatility regime edge.
- liquidity regime edge.
- fast scalp.
- swing hold.
- cuts losses quickly.
- lets winners run.
- adds to winners.
- averages down losers.
- flips often.
- overtrades.
- trades only news spikes.
- avoids low liquidity.
- profitable after fees.
- profitable after copy delay.
- degrades badly after delay.

## Output

- pattern_id.
- wallet.
- pattern_type.
- score.
- evidence_count.
- confidence.
- examples.
- caution flags.

## Règles

- evidence_count minimum.
- no magic label without proof.
- if insufficient -> INSUFFICIENT_DATA.

## Tests

- each pattern with fake fills.
- insufficient data.
- confidence threshold.
- dashboard display.

---

# TICKET 16 — DecisionLedger and EvidenceChain

## But

Chaque décision doit être explicable.

## Tables possibles

`decision_ledger`

```text
decision_id
run_id
wallet
coin
decision_type NO_TRADE|PAPER_INTENT|PAPER_EXIT
created_at
reason_codes
edge_remaining_bps
risk_status
paper_trade_id
feature_hash
evidence_chain_id
```

`evidence_chain`

```text
evidence_chain_id
decision_id
source_health_refs
raw_fill_refs
raw_position_refs
raw_orderbook_refs
raw_mid_refs
raw_candle_refs
feature_hash
wallet_score_ref
lifecycle_event_ref
risk_decision_ref
hash
```

## Must-have

- JSON export.
- search.
- dashboard.
- agent-safe tool.
- hash stable.
- no missing evidence.

## Tests

- no_trade has evidence.
- paper intent has evidence.
- paper exit has evidence.
- search by wallet/coin/reason.
- hash stable.
- tamper changes hash.

---

# TICKET 17 — Dashboard V3 vivant

## But

Un dashboard utilisable, pas décoratif.

## Pages/panels

1. Runtime status.
2. Source health.
3. Rate budget.
4. Wallet leaderboard.
5. Wallet detail.
6. Latest fills/deltas.
7. Position lifecycle.
8. Signal candidates.
9. NoTrade report.
10. Paper portfolio.
11. Paper positions.
12. Paper trades.
13. PnL/equity/drawdown.
14. Market features.
15. Volatility.
16. Orderbook/spread/liquidity.
17. Copy degradation.
18. Risk events.
19. Pattern detector.
20. Backtest runs.
21. Decision ledger.
22. Safety audit.
23. Archive status.
24. Exports.

## Charts

- equity curve.
- realized PnL.
- unrealized PnL.
- drawdown.
- spread.
- liquidity.
- edge remaining.
- latency.
- source staleness.
- wallet score history.
- paper position markers.

## Règles

- empty state honest.
- stale badge.
- no fake points.
- no trade button.
- read-only export.

## Tests

- empty DB.
- real fixtures.
- chart equals DB.
- no buttons.
- stale state.

---

# TICKET 18 — WebSocketSupervisor

## But

Runtime stable.

## Features

- connection manager.
- subscription planner.
- max 10 user-specific wallets.
- market channel subscriptions.
- heartbeat.
- reconnect.
- exponential backoff.
- ack tracking.
- snapshot handling.
- update handling.
- dedupe.
- event persistence.
- gap detection.
- REST reconciliation.
- graceful shutdown.
- bounded duration.
- metrics.

## Event keys

Dedupe by :

- channel.
- wallet.
- coin.
- hash.
- oid.
- tid.
- timestamp.
- isSnapshot.
- raw_hash.

## Tests

- snapshot then update.
- duplicate snapshot ignored.
- reconnect no duplicates.
- gap triggers REST reconcile.
- max wallets.
- max subscriptions.
- source health degraded on fail.

---

# TICKET 19 — Runtime hygiene and archive

## But

Ne plus polluer le repo et éviter les bugs SQLite/logs.

## À faire

- runtime DB in `data/runtime/` or configured path, not `logs/`.
- logs text/jsonl only.
- reports in `data/reports/`.
- archives in `dist/` or `artifacts/`.
- clean archive excludes:
  - `.git`
  - `data`
  - `logs`
  - `runtime`
  - `*.sqlite*`
  - `__pycache__`
  - `.pytest_cache`
  - `.venv`
  - `node_modules`
- backup SQLite with backup API or `VACUUM INTO`.
- detect locked DB.
- bounded audit walk.

## Tests

- clean archive excludes.
- DB not copied raw.
- locked DB warning.
- audit ignores huge folders.
- runtime-check OK.

---

# TICKET 20 — Agent-safe read-only tools

## But

Permettre à Codex/Jules/agents de lire sans jamais agir.

## Manifest

Créer :

`docs/HYPERSMART_AGENT_SAFE_READONLY_MANIFEST.md`

Tools :

- `status.read`
- `source_health.read`
- `wallet.leaderboard`
- `wallet.detail`
- `market.features.read`
- `position_lifecycle.search`
- `decision_ledger.search`
- `paper_portfolio.read`
- `paper_trades.search`
- `backtest.report.read`
- `dashboard.export`
- `archive.status`
- `archive.search`

## Schemas

Créer JSON schemas pour chaque tool.

## Règles

- no write.
- no trade.
- no wallet.
- no order.
- no subprocess.
- inputs sanitized.
- errors graceful.

## Tests

- manifest contains only read verbs.
- schemas validate.
- malicious input rejected.
- no subprocess.
- no mutation.

---

# TICKET 21 — Launcher and config guards

## But

Le lancement Windows doit toujours être sûr.

## Vérifier

`LANCER_HYPERSMART.cmd`

Garde-fous :

- `HL_ENV=paper`
- `HL_ENABLE_MAINNET_EXECUTION=0`
- `HL_ENABLE_TESTNET_EXECUTION=0`
- `HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW`
- `HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW=1`
- `HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=6000`
- `HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY=0`
- `HYPERSMART_SIMULATION_MIN_EDGE_BPS=35`
- `HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE=0.5`
- `HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=12`

## Tests

- launcher contains guards.
- PS1 does not override unsafely.
- env parser defaults safe.
- missing env -> simulation only.

---

# TICKET 22 — Polymarket/Kalshi/dYdX boundaries

## But

Utiliser les idées, pas les runtimes.

## Polymarket/Kalshi

- allowed in docs/research only.
- no runtime import.
- no dependency required.
- no CLOB.
- no API key.
- no wallet/private key.

## dYdX

- preserve files.
- mockable.
- optional.
- not launched by default.
- not imported in Hyperliquid runtime path.
- no conflict with launcher.

## Tests

- no Polymarket runtime imports.
- no CLOB dependency.
- dYdX not imported by default.
- launcher Hyperliquid-first.
- docs can mention BAN safely.

---

# TICKET 23 — Reports Codex must produce

Chaque sprint doit finir avec :

```md
# Rapport final FR

## Résumé
## Fichiers modifiés
## Fichiers créés
## Tests ajoutés
## Commandes lancées
## Résultats
## Preuves sécurité
## Preuves simulation locale
## Preuves no fake data
## Limites restantes
## Prochaine priorité
## Confirmation
- Hyperliquid-only
- simulation locale only
- no /exchange
- no order
- no signature
- no private key
- no wallet connect
- no Polymarket runtime
- dYdX isolé
- PaperEngine préservé
- rien supprimé brutalement
```

---

## F. Prochain sprint recommandé par défaut

Si Codex ne sait pas quoi choisir, il doit faire ce sprint :

# Sprint recommandé : PositionLifecycle + ExitEngine + PaperEngine exits

## Pourquoi

Le bot ne peut pas être jugé rentable s'il sait seulement ouvrir.  
Il doit fermer, réduire, gérer les flips, les partial fills, les coûts et le PnL réalisé.

## Livrables

1. Reconstructor lifecycle.
2. LeaderDelta action OPEN/ADD/REDUCE/CLOSE/FLIP.
3. ExitEngine paper.
4. PaperEngine reduce/close.
5. PnL realized/unrealized/equity/drawdown.
6. DecisionLedger evidence for exits.
7. Dashboard minimal for lifecycle/exits.
8. Backtest fixture for open->close.
9. Tests.

## Tests minimum

```bat
python -m pytest -q tests/test_position_lifecycle_reconstructs_hyperliquid_fills.py
python -m pytest -q tests/test_leader_delta_routes_reduce_close_to_exit_engine.py
python -m pytest -q tests/test_paper_exit_engine_follows_leader_close.py
python -m pytest -q tests/test_paper_engine_reduce_close_realized_pnl.py
python -m pytest -q tests/test_dashboard_lifecycle_and_exits_no_fake.py
python -m hyper_smart_observer.app.main --safety-check
python -m hyper_smart_observer.app.main --audit-safety
```

## Done

- Une ouverture leader peut créer PaperIntent.
- Une réduction leader peut réduire position paper.
- Une fermeture leader peut fermer position paper.
- Un flip ambigu ne crée pas de fake trade.
- PnL réalisé mis à jour.
- Dashboard affiche lifecycle/exits réels.
- Aucune exécution réelle.

---

## G. Objectif court Codex à utiliser avec ce fichier

```text
Lis docs/CODEX_HYPERSMART_MASTER_PLAN_V5.md et AGENTS.md si présent. Utilise Browser pour revérifier tous les GitHub et docs Hyperliquid listés. Travaille local only dans C:\Users\flo\Desktop\Projet invest. Ne supprime rien. Hyperliquid-only, simulation locale only. Applique uniquement la prochaine priorité non terminée du plan, par défaut PositionLifecycle+ExitEngine+PaperEngine exits. Code réel, tests, safety-check, audit-safety, rapport final FR.
```


---

# CODEX_HYPERSMART_MASTER_PLAN_V6 — ROADMAP AUTONOME "NE RIEN OUBLIER"

> Cette V6 est un **addendum total**. Elle ne remplace pas la V5.  
> Elle ajoute des consignes plus détaillées pour qu'un agent de codage autonome sache **quoi chercher**, **quoi coder**, **dans quel ordre**, **comment tester**, et **comment prouver** que le projet avance sans jamais sortir du cadre : **Hyperliquid uniquement, simulation locale uniquement, zéro ordre réel**.

---

## 0. Résumé ultra clair pour l'agent

HyperSmart doit devenir un système local composé de 6 piliers :

1. **Collecter** les vraies données Hyperliquid en lecture seule.
2. **Comprendre** les wallets leaders : fills, positions, lifecycle, comportement.
3. **Décider** avec un RiskEngine deny-by-default.
4. **Simuler** avec le PaperEngine existant, pas avec un nouveau moteur.
5. **Prouver** chaque décision via evidence_chain, hashes, source_health.
6. **Afficher** un dashboard vivant, sans fake data, sans bouton dangereux.

Le projet doit répondre à cette question :

> "Si on avait suivi ces wallets sur Hyperliquid, en paper local, avec frais, spread, slippage, latence, liquidité, sorties, réductions et backtest réaliste, est-ce que la stratégie aurait gagné ou perdu ?"

---

## 1. Rappel absolu : Hyperliquid, pas Polymarket

Les GitHub Polymarket/Kalshi/Prediction markets sont une mine d'idées, mais **le runtime final doit rester Hyperliquid**.

### Autorisé

- Lire les README/docs/src/tests des GitHub pour récupérer des concepts.
- Reproduire les idées utiles en version Hyperliquid read-only.
- Utiliser les stratégies comme inspiration.
- Créer des modules locaux équivalents : scanner, risk, dashboard, backtest, paper, ledger.

### Interdit

- Import runtime Polymarket.
- Import runtime Kalshi.
- CLOB.
- Ethers.
- Private keys.
- Signing.
- Buy/sell/trade action.
- Toute exécution réelle.
- Toute promesse de profit.

---

## 2. Analyse GitHub à faire par Codex avec Browser

Codex doit refaire une passe Browser avant de coder. Il doit écrire ce qu'il a réellement vu.

Créer :

`docs/research/HYPERSMART_GITHUB_DEEP_RESCAN_V6.md`

### Format obligatoire par repo

```md
# Repo: <URL>

## Fichiers ouverts
- README:
- docs:
- src:
- tests:
- scripts:
- config:
- examples:

## Produit observé
Décrire en 5 à 15 lignes ce que le repo essaie de faire.

## Idées KEEP
Ce qu'on garde tel quel comme concept.

## Idées ADAPT_TO_HYPERLIQUID
Ce qu'on transforme en module HyperSmart.

## Idées BAN
Ce qui est interdit.

## Idées DEFER
Ce qui est intéressant mais trop lourd pour maintenant.

## Mapping HyperSmart
| Idée | Module HyperSmart | Priorité | Test |
|---|---|---|---|

## Risques
- sécurité:
- licence:
- fake data:
- exécution:
- complexité:

## Ce que Codex doit coder maintenant
Liste concrète si ce repo apporte une prochaine action.
```

---

## 3. Ce qu'il faut extraire précisément de chaque GitHub

## 3.1 CloddsBot

### Ce qu'il faut comprendre

CloddsBot est un gros produit d'agent trading : WebChat, agents, strategies, whale tracking, copy trading, risk, backtesting, artifacts, code extraction, dashboard, history.  
La valeur pour HyperSmart n'est pas le trading. La valeur est le **produit complet autour de l'observation**.

### À reproduire dans HyperSmart

#### A. Interface produit locale

Créer une expérience dashboard avec sections :

- Overview.
- Scanner.
- Wallets.
- Leaderboard.
- Wallet detail.
- Signals.
- Decisions.
- Paper portfolio.
- Backtests.
- Diagnostics.
- Artifacts/Reports.
- Code/Config status.
- Safety audit.

#### B. Artifacts

Chaque run doit produire un "artifact" lisible :

- run summary JSON.
- source_health JSON.
- scan_features CSV.
- decision ledger JSON.
- paper ledger CSV.
- backtest report JSON.
- dashboard snapshot HTML.
- safety audit report.

#### C. Search

Ajouter une recherche locale :

- rechercher wallet.
- rechercher coin.
- rechercher decision_id.
- rechercher reason_code.
- rechercher feature_hash.
- rechercher paper_trade_id.
- rechercher source failure.

#### D. Decision Ledger SHA-256

Chaque décision doit avoir :

- stable_hash.
- evidence_hash.
- raw_refs.
- source_health refs.
- feature_hash.
- reason_codes.

#### E. Diagnostics

Créer un `doctor` local qui vérifie :

- DB reachable.
- runtime path safe.
- logs path safe.
- no active DB in logs.
- Hyperliquid read-only adapter.
- no `/exchange`.
- no private key env.
- no Polymarket runtime.
- dashboard export OK.
- paper engine state OK.
- recent source_health OK/degraded.

### À bannir

- "one command away from trading".
- credentials setup.
- execution.
- DEX/EVM.
- payments.
- token launch.
- autonomous real orders.

### Modules précis

- `dashboard/`
- `diagnostics/doctor.py`
- `artifacts/`
- `search/`
- `decision_ledger/`
- `safety/`

### Tests précis

- `test_doctor_detects_forbidden_exchange.py`
- `test_artifacts_created_per_run.py`
- `test_search_finds_decision_by_hash.py`
- `test_dashboard_no_trade_buttons.py`
- `test_no_secret_prompt_or_env_wizard.py`

---

## 3.2 Harrier / Prediction-Markets-Trading-Bot-Toolkits

### Ce qu'il faut comprendre

Harrier apporte l'idée "one core, one risk layer, adapter stack, multiple strategies".  
Chez nous, la version correcte est :

> one observation core, one paper core, one risk layer, read-only adapters.

### À reproduire

#### A. Architecture uniforme

Créer un contrat commun :

- `ReadOnlyVenueAdapter`
- `ObservationCore`
- `PaperCore`
- `RiskEngine`
- `StrategyResearchModule`

#### B. Stratégies transformées

Harrier contient plusieurs stratégies. Codex doit les convertir ainsi :

| Stratégie source | Adaptation HyperSmart |
|---|---|
| Copy Trading | Wallet leader simulation |
| Orderbook Imbalance | MarketSignalFeatures.depth_imbalance |
| On-chain Whale Signal | Hyperliquid wallet/fill delta detector |
| Cross-market arbitrage | DEFER, seulement edge comparator |
| Direction hunting | Pattern detector, pas ordre |
| Spread farming | BAN runtime, garder spread/liquidity analytics |
| Market making | BAN |
| Resolution sniper | BAN |
| Sports execution | BAN |
| BTC arbitrage | DEFER, seulement volatility/latency lesson |

#### C. Risk layer unique

Aucun module ne doit décider seul. Tout passe par `RiskEngine`.

### Modules

- `core/observation_core.py`
- `core/paper_core.py`
- `adapters/base.py`
- `risk/engine.py`
- `strategies/research_registry.py`

### Tests

- `test_all_paths_call_risk_engine_before_paper_intent.py`
- `test_adapter_contract_readonly_only.py`
- `test_strategy_registry_contains_no_execution_strategy.py`
- `test_orderbook_imbalance_is_feature_not_trade.py`

---

## 3.3 MrFadi Polymarket Bot

### Ce qu'il faut comprendre

Même si le repo est Polymarket/trading, il apporte une idée importante : **ne pas copier n'importe quel wallet**.  
Il faut scorer sévèrement, filtrer, réduire la taille paper, et créer des halts.

### À reproduire

#### A. WalletScoreV2

Implémenter ou renforcer :

```text
wallet
period_start
period_end
fills_count
closed_trades_count
active_days
recent_activity_score
realized_pnl
closed_pnl
fees_paid
winrate
profit_factor
avg_win
avg_loss
payoff_ratio
max_drawdown
sharpe
sortino
calmar
consistency_score
pnl_concentration
one_big_win_ratio
coin_concentration
leverage_risk
liquidation_count
avg_holding_time
data_quality_score
```

#### B. CopyabilityScore

```text
wallet_score_ref
copyability_score
copy_delay_sensitivity
liquidity_fit
average_copy_degradation_bps
leader_slippage_risk
position_size_fit
exit_followability
confidence
```

#### C. Risk flags

- INSUFFICIENT_HISTORY.
- ONE_BIG_WIN.
- HIGH_DRAWDOWN.
- LOW_PROFIT_FACTOR.
- LOW_WINRATE.
- OVERCONCENTRATED.
- INACTIVE.
- SUSPICIOUS.
- LOW_DATA_QUALITY.
- HIGH_LIQUIDATION_RISK.
- TOO_FAST_TO_COPY.
- EXIT_NOT_FOLLOWABLE.

#### D. Paper sizing

Sizing conservateur :

- base size.
- reduce after loss streak.
- reduce if liquidity low.
- reduce if wallet confidence low.
- cap per coin.
- cap per wallet.
- cap portfolio.
- hard zero if risk flags severe.

### Tests

- `test_wallet_score_rejects_one_big_win.py`
- `test_copyability_penalizes_copy_delay.py`
- `test_sizing_reduced_after_loss_streak.py`
- `test_wallet_with_insufficient_history_not_leader.py`
- `test_exit_not_followable_blocks_copy.py`

---

## 3.4 polymarket_lp_tool

### Ce qu'il faut comprendre

Le plus utile est la discipline temps réel :

- WS-first.
- REST reconciliation.
- deterministic simple rules.
- cooldown.
- mid stability.
- anti-jump.
- structured tracing.
- persistence.

### À reproduire

#### A. WS-first shortlist

- REST broad scan.
- score wallets.
- shortlist max 10 user-specific.
- WS on shortlist only.
- REST reconcile every N seconds/minutes.

#### B. Mid stability

Créer `MidStabilityFilter` :

```text
coin
window_ms
mid_values
median_mid
ema_mid
max_jump_bps
is_stable
reason
```

Si jump brutal :

- NoTradeReason.MID_JUMP.
- dashboard badge.
- source_health degraded if repeated.

#### C. Cooldowns

Cooldowns :

- wallet+coin+action.
- wallet global.
- coin global.
- after failed signal.
- after paper loss.
- after source degradation.

#### D. Structured tracing

Chaque run doit logguer en JSONL :

- event_type.
- run_id.
- wallet.
- coin.
- decision_id.
- source_health.
- reason_codes.
- no secrets.

### Tests

- `test_mid_jump_blocks_signal.py`
- `test_cooldown_blocks_duplicate_wallet_coin_action.py`
- `test_rest_reconcile_recovers_missing_ws_fill.py`
- `test_jsonl_logs_have_no_secrets.py`

---

## 3.5 PolyWeather

### Ce qu'il faut comprendre

PolyWeather apporte surtout le concept : **dashboard authoritative + stale state**.  
Si les données ne sont pas fraîches, l'UI ne doit pas faire semblant.

### À reproduire

#### A. Authoritative Snapshot

Créer un `DashboardSnapshot` qui n'est généré qu'à partir de données validées.

Champs :

- snapshot_id.
- generated_at.
- runtime_status.
- source_health_summary.
- stale_sources.
- latest_collection_run.
- paper_portfolio_summary.
- no_trade_summary.
- risk_summary.
- warning_banner.

#### B. Stale policy

Règle :

- source stale -> signal not paper_ready.
- dashboard stale badge.
- paper intent impossible.
- backtest peut utiliser historical stale state explicitement.

#### C. Fallback refresh

Si WS stale :

- marquer stale.
- déclencher REST reconcile.
- ne pas inventer.
- ne pas cacher l'erreur.

### Tests

- `test_stale_source_blocks_paper_ready.py`
- `test_dashboard_snapshot_marks_stale.py`
- `test_ws_stale_triggers_rest_reconcile.py`
- `test_refresh_pending_does_not_fake_values.py`

---

## 3.6 Composio arbitrage bot

### Ce qu'il faut comprendre

Composio apporte une API simple de contrôle/état, mais contient des actions buy interdites.

### À reproduire

#### A. API read-only locale

Endpoints ou CLI read-only :

- health.
- status.
- scanner state.
- current signal.
- current no_trade.
- source health.
- latest run.
- paper portfolio.

#### B. Scanner controls sûrs

Si contrôles locaux existent :

- start scanner simulation.
- stop scanner simulation.
- pause scanner.
- export status.

Aucun contrôle ne doit trader.

### Tests

- `test_status_endpoint_readonly.py`
- `test_scanner_start_stop_does_not_trade.py`
- `test_current_signal_has_no_buy_action.py`

---

## 3.7 Awesome Prediction Market Tools

### Ce qu'il faut comprendre

Ce repo est une carte produit. Il montre toutes les familles d'outils à couvrir.

### À reproduire dans dashboard

Catégories :

- wallet analytics.
- portfolio tracking.
- dashboards.
- alerts.
- data exports.
- historical snapshots.
- leaderboards.
- watchlists.
- smart/whale/suspicious/fresh labels.
- liquidity/orderbook depth.
- spreads.
- historical replay.
- source health.
- copyability score.

### À coder

- watchlist import/export.
- wallet labels.
- leaderboard filters.
- local alerts disabled by default.
- export center.
- historical snapshot browser.

### Tests

- `test_watchlist_import_validates_wallets.py`
- `test_alerts_disabled_by_default.py`
- `test_wallet_label_requires_evidence.py`
- `test_export_center_has_no_fake_data.py`

---

## 3.8 PolyTerm

### Ce qu'il faut comprendre

PolyTerm est essentiel pour agents :

- CLI/TUI.
- local SQLite.
- agent-ready manifest.
- JSON schemas.
- MCP-like read-only tools.
- doctor.
- llms.txt.
- exports.
- replay.
- safe inputs.
- graceful failures.

### À reproduire

#### A. Agent-safe manifest

Créer :

- `docs/HYPERSMART_AGENT_SAFE_READONLY_MANIFEST.md`
- `docs/llms.txt`
- `docs/llms-full.txt`
- `schemas/*.json`

#### B. Tools

- status.read.
- source_health.read.
- wallet.leaderboard.
- wallet.detail.
- wallet.patterns.read.
- market.features.read.
- position_lifecycle.search.
- decision_ledger.search.
- paper_portfolio.read.
- paper_trades.search.
- backtest.report.read.
- dashboard.export.
- archive.status.
- archive.search.

#### C. Safety

- read-only verbs only.
- no shell/subprocess.
- sanitize inputs.
- max limit on results.
- graceful errors.
- schemas tested.

### Tests

- `test_agent_manifest_readonly_only.py`
- `test_agent_schemas_validate.py`
- `test_agent_tools_reject_bad_input.py`
- `test_agent_tools_do_not_mutate_db.py`

---

## 3.9 mlmodelpoly

### Ce qu'il faut comprendre

Ce repo apporte le pipeline features temps réel :

- WS collector.
- OHLCV.
- CVD.
- VWAP.
- volatility.
- fair value.
- edge.
- TUI.
- REST latest endpoints.
- metrics.

### À reproduire côté Hyperliquid

#### A. Bars

Créer bars locales depuis candles/trades :

- 1m.
- 5m.
- 15m.
- OHLCV.
- return.
- volume if available.
- realized volatility.

#### B. Trade flow

Si trades disponibles :

- buy volume.
- sell volume.
- CVD approximation.
- trade_count.
- large_trade_count.
- aggressive_flow_score.

Si non disponibles :

- None/degraded.

#### C. Edge API interne

Créer un endpoint/payload local :

- latest features.
- latest bars.
- latest edge.
- latest source health.

### Tests

- `test_bars_from_candle_snapshot.py`
- `test_trade_flow_from_recent_trades.py`
- `test_trade_flow_missing_degraded.py`
- `test_latest_features_payload_schema.py`

---

## 3.10 polyrec

### Ce qu'il faut comprendre

polyrec apporte l'idée de CSV très riche et de dashboard terminal.

### À reproduire

#### A. Export scan_features très riche

Colonnes minimales :

```text
run_id,timestamp,wallet,coin,lifecycle_event,leader_action,
source_ts,latency_ms,current_mid,mid_source,best_bid,best_ask,
spread_bps,bid_depth_1,ask_depth_1,bid_depth_5,ask_depth_5,
depth_imbalance,microprice,depth_slope,trade_count,trade_flow_delta,
candle_return_1m,candle_return_5m,realized_vol_bps,range_bps,atr_bps,
liquidity_score,leader_reference_price,copy_degradation_bps,
edge_remaining_bps,data_quality,source_health_ref,feature_hash,
decision_id,no_trade_reason,paper_intent_id
```

#### B. Terminal status

CLI optional :

- current run.
- source health.
- latest no_trade.
- paper PnL.
- top wallets.
- latest features.

### Tests

- `test_scan_features_export_has_full_schema.py`
- `test_scan_features_json_csv_parity.py`
- `test_feature_row_links_decision_id.py`

---

## 3.11 prediction-market-backtesting + benchmark ideas

### Ce qu'il faut comprendre

Le meilleur backtest doit être event-driven et sans lookahead.

À adapter :

- staged loading.
- local cache.
- orderbook replay.
- trade replay.
- same strategy/risk runtime and backtest.
- reports.
- deterministic episodes.
- cost-aware simulation.

### À coder

#### A. Backtest episode

```text
episode_id
source
wallets
coins
start_ts
end_ts
events_count
features_count
fills_count
book_snapshots_count
```

#### B. Replay event types

- MARKET_MID.
- L2_BOOK.
- CANDLE.
- TRADE.
- LEADER_FILL.
- LIFECYCLE_EVENT.
- SIGNAL_CANDIDATE.
- RISK_DECISION.
- PAPER_OPEN.
- PAPER_REDUCE.
- PAPER_CLOSE.
- NO_TRADE.
- SOURCE_STALE.
- WS_GAP.
- REST_RECONCILE.

#### C. No lookahead rules

- features must use only data <= event time.
- paper fill uses next available market snapshot or explicit model.
- delayed scenarios use shifted observation time.
- no future closedPnl to decide entry.

### Tests

- `test_backtest_no_lookahead.py`
- `test_backtest_event_order_deterministic.py`
- `test_backtest_same_risk_as_runtime.py`
- `test_backtest_delayed_copy_scenario.py`
- `test_backtest_report_metrics_schema.py`

---

## 3.12 polybot

### Ce qu'il faut comprendre

polybot est utile pour architecture future, mais dangereux/lourd maintenant.

### À garder en DEFER

- service boundaries.
- ingestion.
- analytics.
- monitoring.
- metrics.
- replication scoring.
- strategy research.
- dashboards.

### À ne pas faire

- ClickHouse.
- Redpanda/Kafka.
- Grafana deployment.
- Prometheus setup.
- executor-service.
- live bot.
- Java stack migration.

### Adaptation maintenant

Créer des interfaces simples :

- `ingestion/`
- `analytics/`
- `monitoring/`
- `research/`

Mais implémentation SQLite locale seulement.

### Tests

- `test_no_clickhouse_required.py`
- `test_no_executor_service.py`
- `test_local_sqlite_default.py`

---

## 3.13 Polymarket/agents

### Ce qu'il faut comprendre

Le repo peut inspirer :

- typed schemas.
- connectors.
- RAG.
- evidence reports.
- agent task decomposition.

### À reproduire

- `EvidenceReportBuilder`.
- `WalletThesisReport`.
- `DecisionExplainer`.
- `ResearchConnector` offline/read-only.
- Pydantic models for reports.

### À bannir

- Polymarket API runtime.
- CLOB.
- trade actions.
- private key.
- signing.
- autonomous bet placement.

### Tests

- `test_research_connector_offline_only.py`
- `test_decision_explainer_uses_existing_evidence.py`
- `test_no_polymarket_agent_trade_actions.py`

---

## 3.14 Lightweight Charts

### Ce qu'il faut comprendre

Lightweight Charts sert uniquement à afficher les vraies données.

### À coder

Séries :

- equity line.
- realized PnL line.
- unrealized PnL line if mids available.
- drawdown area.
- spread line.
- liquidity line.
- edge remaining line.
- copy degradation line.
- source latency line.
- staleness line.
- wallet score line.
- candlesticks from real candles if available.
- markers for leader fills.
- markers for paper opens/reduces/closes.
- markers for no_trade reasons.

### Règles

- empty data -> empty state.
- stale -> badge.
- no generated random movement.
- no smoothing that changes truth; smoothing only visual and labeled.

### Tests

- `test_chart_series_from_db_only.py`
- `test_empty_chart_no_fake_points.py`
- `test_trade_markers_match_paper_ledger.py`

---

## 4. Nouveaux éléments probablement oubliés à ajouter au projet

## 4.1 Funding and fees context

Hyperliquid perps peuvent avoir funding/fees. Même si non branché au début, prévoir :

- userFees.
- fundingHistory/userFunding if rate-budget OK.
- fee tier.
- fee token.
- funding impact in backtest later.

À coder en DEFER ou PARTIAL :

- `CostModelV2`
- `FundingContext`

Tests :

- fee estimate included.
- funding unavailable -> None/degraded.
- no fake funding.

## 4.2 Liquidation and margin risk

Pour leader analysis :

- liquidation fills.
- marginSummary.
- crossMarginSummary.
- leverage/margin usage if available.
- high liquidation penalty.
- excessive leverage flag.

Tests :

- liquidation event creates risk flag.
- high margin usage lowers copyability.
- missing margin data degraded.

## 4.3 Open interest / crowded trade risk

Si données dispo via official/market data :

- crowded coin flag.
- too many leaders same direction.
- cluster risk.
- correlated exposure.

Sinon DEFER.

## 4.4 Correlation and portfolio exposure

Paper portfolio doit éviter :

- 10 positions corrélées.
- same coin overexposure.
- same wallet overexposure.
- same direction cluster.

À coder :

- `PortfolioRiskEngine`
- exposure_by_coin.
- exposure_by_direction.
- exposure_by_wallet.
- max_correlated_positions.

Tests :

- overexposure blocks new PaperIntent.
- reduce frees exposure.
- dashboard shows exposure.

## 4.5 Signal freshness budget

Déjà max age 6000ms, mais rendre visible :

- observed_time.
- leader_time.
- local_received_ts.
- decision_time.
- total_latency_ms.
- staleness_ms.
- max allowed.
- reason if stale.

Tests :

- stale signal no trade.
- dashboard shows latency breakdown.

## 4.6 Clock skew and timestamp sanity

Ajouter :

- detect future timestamps.
- detect old source_ts.
- monotonic run time.
- timezone UTC.
- local clock warnings.

Tests :

- future timestamp degraded.
- negative latency guarded.

## 4.7 Data dedupe everywhere

Dedupe keys :

- fill hash.
- tid.
- oid.
- wallet+coin+time+px+sz.
- ws raw_hash.
- lifecycle event hash.
- paper intent idempotency key.

Tests :

- duplicate fill not double counted.
- duplicate lifecycle not double trade.
- duplicate close not double close.

## 4.8 Idempotent run design

Relancer un run ne doit pas créer doubles positions.

À coder :

- collection_run id.
- idempotency_key.
- unique constraints.
- upsert safe.
- paper action idempotency.

Tests :

- same event replay twice same result.
- no duplicate paper trade.

## 4.9 Config and thresholds explainability

Tous les seuils doivent être visibles :

- min edge.
- max signal age.
- min liquidity.
- max spread.
- max copy degradation.
- max positions.
- stop rules.
- scoring thresholds.

Dashboard doit montrer :

- active config.
- source of config.
- defaults.
- unsafe overrides blocked.

Tests :

- config export.
- unsafe config rejected.
- launcher guards win over unsafe env.

## 4.10 Synthetic fixtures only in tests

Le mot fake est autorisé seulement dans tests/fixtures.

Règle :

- test fixtures clearly named.
- dashboard runtime never uses fake.
- sample data never loaded as live.

Tests :

- no fake markers in runtime dashboard.
- fixture path excluded from live.

---

## 5. Plan d'exécution ultra précis pour le prochain agent

Codex doit suivre cet ordre si rien n'est déjà fait.

### Phase 1 — Audit et recherche

1. Lire V6.
2. Lire AGENTS.md.
3. Browser deep scan des GitHub.
4. Écrire `HYPERSMART_GITHUB_DEEP_RESCAN_V6.md`.
5. Écrire `HYPERSMART_CURRENT_CODE_AUDIT_V6.md`.

### Phase 2 — Choisir priorité

Si `PositionLifecycle` ou `ExitEngine` absent/partiel, priorité absolue :

- PositionLifecycle.
- LeaderDelta.
- ExitEngine.
- PaperEngine reduce/close.
- PnL realized.
- tests.

Si déjà fait, priorité suivante :

- EvidenceChain SQL.
- Volatility live.
- Backtest replay.
- Dashboard V3.
- WS supervisor.
- Agent-safe manifest.
- Archive/security.

### Phase 3 — Implémenter vertical slice

Ne pas coder 20 modules à moitié. Faire une preuve verticale :

```text
raw Hyperliquid fills fixture
-> NormalizedFill
-> PositionLifecycleEvent
-> LeaderDelta
-> SignalCandidate or PaperExitIntent
-> RiskEngine
-> PaperEngine open/reduce/close
-> DecisionLedger evidence
-> Paper PnL
-> Dashboard payload
-> Backtest parity
```

### Phase 4 — Tests obligatoires de la vertical slice

- fixture open long.
- fixture add.
- fixture reduce.
- fixture close.
- fixture flip ambiguous.
- paper open.
- paper reduce.
- paper close.
- realized PnL.
- no fake PnL.
- evidence chain.
- dashboard.
- no /exchange.
- no Polymarket runtime.

### Phase 5 — Rapport FR

Le rapport doit dire :

- ce qui a été lu sur GitHub.
- ce qui a été codé.
- ce qui a été adapté à Hyperliquid.
- ce qui a été banni.
- tests passés.
- limites.
- prochaine priorité.

---

## 6. Prompt court Codex pour utiliser cette V6

```text
Lis docs/CODEX_HYPERSMART_MASTER_PLAN_V6.md et AGENTS.md. Utilise Browser pour revérifier tous les GitHub/docs Hyperliquid listés, puis écris les rapports de recherche/audit demandés. Travaille local only dans C:\Users\flo\Desktop\Projet invest. Ne supprime rien. Hyperliquid-only, simulation locale only. Applique une seule vertical slice prioritaire, par défaut PositionLifecycle+ExitEngine+PaperEngine reduce/close+PnL+Evidence+Dashboard. Code réel, tests, safety-check, audit-safety, rapport final FR.
```

---

## RÈGLE ABSOLUE — SIMULATION BRANCHÉE SUR LE MARCHÉ RÉEL, AUCUNE DÉMO

> Ajoutée à la demande explicite de l'utilisateur. Cette règle prime sur toute interprétation contraire.

La simulation HyperSmart est **LOCALE** (paper / mock USDC) mais **OBLIGATOIREMENT branchée sur le marché RÉEL Hyperliquid**. C'est du **« trading réel simulé localement »**, PAS une démo.

**Interdiction absolue** de tout mode `demo`, `fake`, `synthetic`, `placeholder`, `mock_tick`, `seeded`, ou de toute donnée/mouvement inventé — y compris en repli quand le scan échoue ou que le moteur ne démarre pas. Si une donnée manque : afficher honnêtement l'état (0 position, solde inchangé, source `DEGRADED`/`MISSING`) — **JAMAIS** de tick synthétique, **JAMAIS** de faux PnL, **JAMAIS** de « démo locale ».

Obligations:

- **Signaux, ouvertures, ADD, REDUCE, fermetures** proviennent UNIQUEMENT des vraies données Hyperliquid read-only (`allMids`, `l2Book`, `userFills`, `userFillsByTime`, `trades`, `candleSnapshot`, WS public).
- **Gains & pertes = ce qui se serait réellement passé si on s'était placé en réel** : mark-to-market au **vrai prix mainnet**, après **frais + spread + slippage + latence + dégradation de copie** réalistes. Le solde paper reflète un placement réel hypothétique, pas une approximation décorative.
- **Solde de départ 1000 $ mock USDC** ; il ne bouge QUE via des positions paper ouvertes à partir de vrais signaux et **marquées au vrai prix** (réalisé + non-réalisé).
- Le label peut dire « LOCAL » uniquement au sens « moteur paper exécuté localement » — **jamais** au sens « déconnecté du marché ».

**Frontière dure inchangée** : aucun ordre réel, aucune clé privée, aucune signature, aucun dépôt/retrait. Lecture seule + simulation paper sur données marché réelles.

---

## ÉTAT D'INSTALLATION & ÉCARTS (audit 2026-06-18)

Audit du dépôt local vs feuille de route V7. La majorité des modules existent et sont branchés.

### Présent & branché (vérifié)
- `hyper_smart_observer/` : `agent_tools/` (readonly_manifest.py, schemas.py), `pipeline/source_health.py`,
  `market_signals/` (mid_stability, orderbook_features, volatility, edge), `ledger/` (decision_ledger + evidence),
  `position_lifecycle/` (+ lifecycle_summary, exit), `paper_trading/` (simulator + exit_engine), `backtesting/`
  (replay + event_replay + runtime_parity), `patterns/` (pattern_detector + INSUFFICIENT_DATA), `scoring/` (wallet score V2),
  `risk_engine/`, `copy_mode/`, `dashboard/`.
- `src/hl_observer/` runtime : moteur `ui` (réparé), `/api/simulation/overview` + `/api/simulation/status`
  (status_routes.py, mark-to-market au vrai prix), WS-resilience en pièces (reconnect, dedupe, heartbeat,
  freshness_guard, event_router, hot_watch_rotation), collecte (discover-markets/wallets, bootstrap, scan-queue).
- Sécurité : `--safety-check` + `--audit-safety` = 14/14 OK (0 ordre, 0 clé, 0 signature).

### Écarts réels (à traiter)
1. **`collect-all` (CLI)** — perdu lors d'une restauration. → **RÉ-AJOUTÉ** comme module autonome
   `hl_observer/collection/run_collect_all.py` (sans toucher au gros `cli.py`). Lance : discover markets ->
   discover wallets -> bootstrap-top-wallets -> scan-wallet-queue. Statut : FAIT.
2. **`docs/llms.txt` + `docs/llms-full.txt`** (V7 §3.8, agent discoverability) — manquaient. → **CRÉÉS**. Statut : FAIT.
3. **Schémas `*.schema.json`** (V7 §3.8) — des schémas Python existent (`agent_tools/schemas.py`) mais pas de
   fichiers JSON Schema. → DEFER (faible valeur ; les schémas Python suffisent au runtime).
4. **`venues/` (abstraction multi-venue, Harrier)** — pas de package `venues/` formel. Non bloquant :
   `hyperliquid_client` est déjà l'adaptateur read-only ; le `MockAdapter` est couvert par les fakes de tests ;
   dYdX reste isolé. → DEFER (purement architectural).
5. **WS « supervisor » unifié** — toutes les briques existent (reconnect/backoff/dedupe/heartbeat/fallback/freshness)
   mais pas une seule façade `ws_supervisor`. → Optionnel (regroupement cosmétique).
6. **Scaling shortlist 30 → 500** — limite de **données/process**, PAS un gap de code : seuls ~30 wallets sont
   scorés dans `TopWallet`. Lever : exécuter `run_collect_all` / `scan-wallet-queue` dans le temps (réseau borné).
   Si on veut afficher >50 leaders, monter `settings.copy_trading.top_leaders` (réglage, à faire proprement).

### GitHub (rescan)
Rescan KEEP/ADAPT/BAN/DEFER déjà consigné dans `docs/research/HYPERSMART_GITHUB_RESCAN_CODEX.md` ; matrice inchangée ;
aucun code externe copié (idées réimplémentées). Pas de nouvelle navigation nécessaire ce tour.

### Garde-fous (inchangés)
Édition des très gros fichiers (`cli.py`, `routes.py`) = via NOUVEAUX petits modules importés, jamais en place
(risque de troncature). Restauration le cas échéant via `git show HEAD:...`.

### Écarts comblés (passe 2026-06-18 #2)
- **Schémas JSON agent-safe** (V7 §3.8) : générés dans `docs/schemas/*.schema.json` à partir du manifest réel
  (`status.read`, `wallet.leaderboard`, `decision_ledger.search`, `dashboard.export`, `source_health.read` + capacités interdites). FAIT.
- **WS supervisor unifié** (V7 §10) : `hyper_smart_observer/realtime_monitor/ws_supervisor.py` compose
  backoff reconnect + dedupe snapshot + heartbeat→fallback REST + cap 10 streams ; testé. FAIT.
- **`venues/` formel** : maintenu DEFER (le `hyperliquid_client` est déjà l'adaptateur read-only ; créer un package
  vide serait du code mort). À faire seulement si un 2e venue read-only réel est ajouté.

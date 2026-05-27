# HyperSmart Observer - Recherche sur le "bot magique" Hyperliquid / Claude

Date de recherche: 2026-05-24

Statut: document de recherche et de conception. Ce document ne decrit pas un
systeme de trading reel, ne promet aucun resultat financier, et ne doit jamais
etre transforme tel quel en execution mainnet.

## Resume franc

Le fameux "bot magique" n'est pas magique. La version la plus credible observee
est une architecture de copy-observation en trois jobs:

1. Construire chaque jour une shortlist de wallets depuis le leaderboard
   Hyperliquid.
2. Toutes les 5 minutes par defaut, comparer les positions/fills/orders des
   leaders avec le snapshot precedent pour detecter les deltas.
3. Produire des rapports, un portefeuille paper local et un `no_trade_report`.

Ce qui peut etre reproduit serieusement:

- discovery leaderboard et explorer;
- validation stricte des adresses completes;
- shortlist de wallets avec filtres de qualite;
- observation read-only via `/info` et WebSocket;
- detection `OPEN_LONG`, `OPEN_SHORT`, `ADD`, `INCREASE`, `REDUCE`,
  `CLOSE_LONG`, `CLOSE_SHORT`, `UNKNOWN`;
- scoring prudent;
- calcul obligatoire de `edge_remaining_bps`;
- paper trading local pessimiste en mock USDC;
- rapports expliquant chaque refus.

Ce qui ne doit pas etre reproduit:

- ordres reels;
- mainnet;
- signature;
- cle privee;
- endpoint `/exchange`;
- promesse de benefice certain;
- LLM dans le hot path;
- transformation d'un score en instruction de trading.

## Mise a jour 2026-05-27 - temps reel simulation

Le chemin actif du dashboard (`src/hl_observer`) utilise maintenant un moteur
de notation explicite pour le mode "comme si le bot ouvrait une position", sans
jamais produire d'ordre:

- module: `src/hl_observer/copying/realtime_magic_score.py`;
- entree: delta leader frais + prix leader + mid courant + consensus + score
  leader + exposition locale;
- sortie: `ACCEPT_LOCAL_SIMULATION` ou `REJECT_NO_TRADE`;
- edge restant obligatoire: un signal sans `edge_remaining_bps` mesurable est
  refuse;
- fenetre realtime dure: 10 minutes maximum, avec penalite de delai continue;
- capital local: 1000 USDT simules;
- taille par position plafonnee: 50 USDT;
- exposition totale plafonnee: 200 USDT;
- les evenements anterieurs au lancement UI restent ignores.
- l'etat de session est persiste dans `data/runtime/ui_simulation_state.json`,
  donc une reconnexion ne remet plus automatiquement le PnL a 1000 USDT.

La notation reprend les idees publiques observees (3 jobs, realtime/polling,
sizing proportionnel/capped, deviation de prix, max exposure, ignore old fills)
mais supprime toute partie executable: pas de private key, pas de signature,
pas de `/exchange`, pas de testnet executor actif.

## Sources consultees

| Source | Classement | Ce que la source apporte | Lien |
|---|---|---|---|
| Article LearnWithMeAI "I Built a Claude Trading Bot That Copies Hyperliquid Millionaires" | `article_marketing + implementation_hint` | Architecture 3 jobs, top 5 wallets, boucle 5 minutes, paper portfolio, Slack, GitHub Actions + cron-job.org | https://www.learnwithmeai.com/p/claude-trading-bot-hyperliquid |
| Hyperliquid docs - Info endpoint | `official_source` | `/info`, pagination, `allMids`, `openOrders`, `frontendOpenOrders`, `userFills`, `userFillsByTime`, `orderStatus`, `historicalOrders`, `portfolio`, `userFees` | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint |
| Hyperliquid docs - WebSocket subscriptions | `official_source` | `allMids`, `l2Book`, `trades`, `orderUpdates`, `userEvents`, `userFills`, `userFundings`, champs `dir`, `closedPnl`, `startPosition` | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions |
| Hyperliquid docs - Rate limits and user limits | `official_source` | 1200 poids REST/min/IP, poids info, limites WebSocket, 10 users uniques pour subscriptions user-specific, explorer plus couteux | https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits |
| Hyperliquid docs - Testnet faucet | `official_source` | 1,000 mock USDC testnet via faucet officiel, utile uniquement pour tests futurs, pas pour Batch 1 | https://hyperliquid.gitbook.io/hyperliquid-docs/onboarding/testnet-faucet |
| Hyperliquid Explorer public | `public_app_source` | Blocks, transactions, hashes, recherche par block/hash/adresse, mais addresses visibles souvent tronquees dans l'UI | https://app.hyperliquid.xyz/explorer |
| MaxIsOntoSomething/Hyperliquid_Copy_Trader | `github_repo_inspiration` | WebSocket monitor, sizing proportionnel, caps de notionnel, simulated mode, skip min notional | https://github.com/MaxIsOntoSomething/Hyperliquid_Copy_Trader |
| Dwellir gRPC copy-trading examples | `github_repo_inspiration + external_provider_docs` | `StreamFills`, dry-run, duplicate guard, copy percentage, min/max position, sync positions before close | https://github.com/dwellir-public/gRPC-code-examples/tree/main/copy-trading-bot |
| Dwellir StreamFills docs | `external_provider_docs` | Schema fills, `dir`, `closedPnl`, `startPosition`, maker/taker via `crossed`, `fee`, stream real-time | https://www.dwellir.com/docs/hyperliquid/stream_fills |
| Chainstack Hyperliquid copy-trading WebSocket guide | `external_provider_docs` | Etat de sequence, WebSocket `orderUpdates` + `userEvents`, sizing dynamique, precision d'actifs | https://docs.chainstack.com/docs/hyperliquid-copy-trading-websocket |
| chainstacklabs/hyperliquid-trading-bot | `github_repo_inspiration` | WebSocket, risk limits, dashboard/config patterns, testnet examples; parties execution interdites ici | https://github.com/chainstacklabs/hyperliquid-trading-bot |
| ThisNewMark/perplobster | `github_repo_inspiration` | Dashboard, SQLite metrics, bots extensibles, emergency stop, config; execution interdite ici | https://github.com/ThisNewMark/perplobster |
| zkOSAI/hyperliquid-copy-trading-bot | `github_repo_inspiration + rejected_execution_parts` | Exemple simple de mirroring, API wallet/private key, leverage cap; trop execution-first pour HyperSmart | https://github.com/zkOSAI/hyperliquid-copy-trading-bot |

## Verification du recit viral

L'article LearnWithMeAI, publie le 2026-05-20, affirme construire avec Claude
Code un bot qui observe les 5 meilleurs wallets Hyperliquid toutes les 5
minutes et applique le resultat a un portefeuille paper. Le texte dit
explicitement qu'il n'y a pas encore de vrai argent, seulement du paper.

Le passage cle est l'architecture:

- Job A: quotidien a 09:13 UTC, pull leaderboard, filtrage bruit, ranking par
  execution quality, ecriture shortlist JSON.
- Job B: toutes les 5 minutes, lit shortlist, fetch positions ouvertes,
  compare au snapshot precedent, convertit les nouveaux deltas en evenements
  paper.
- Job C: toutes les 30 minutes, lit l'etat, calcule activite/PnL 24h, envoie un
  rapport Slack, read-only.

Conclusion: le contenu viral est utile comme architecture produit, pas comme
preuve qu'un systeme peut sortir parfaitement avant les pertes. La partie
reproductible est la chaine de donnees; la partie "magique" doit etre rejetee.

## Ce que Hyperliquid rend possible

La documentation officielle confirme que `/info` permet de recuperer en lecture:

- `allMids`: prix mids multi-assets;
- `openOrders` et `frontendOpenOrders`: ordres ouverts d'un utilisateur;
- `userFills`: fills recents, limite officielle de 2000 fills;
- `userFillsByTime`: fills par periode, au plus 2000 fills par reponse et
  seulement les 10000 plus recents;
- `clearinghouseState`: positions et resume de marge;
- `orderStatus`: statut d'un ordre par oid/cloid;
- `historicalOrders`: ordres historiques recents;
- `portfolio`, `userFees`, `userRateLimit`.

La documentation officielle confirme aussi que les fills contiennent les champs
utiles:

- `coin`;
- `px`;
- `sz`;
- `side`;
- `time`;
- `startPosition`;
- `dir`;
- `closedPnl`;
- `hash`;
- `oid`;
- `crossed`;
- `fee`;
- `tid`;
- `feeToken`.

Ces champs suffisent a construire une premiere classification des deltas sans
inventer de position.

## Limites API a respecter

Les limites importantes a coder dans HyperSmart:

- REST: poids agreges par IP.
- `l2Book`, `allMids`, `clearinghouseState`, `orderStatus`,
  `spotClearinghouseState`, `exchangeStatus`: poids faible documente.
- Beaucoup d'autres endpoints `/info`: poids plus eleve.
- `userFills`, `userFillsByTime`, `historicalOrders`, `fundingHistory`,
  `userFunding`, `userTwapSliceFills`: poids additionnel par nombre d'elements.
- Explorer API: poids eleve; a utiliser prudemment, ou comme source manuelle.
- WebSocket: maximum documente de connexions/subscriptions, dont maximum 10
  users uniques sur les subscriptions user-specific.

Implication produit: scanner large via REST borne + shortlist reduite en
WebSocket. Ne pas suivre 1000 wallets en `userFills` WebSocket.

## Architecture cible HyperSmart

```text
Job A - Leaderboard / discovery daily
  public leaderboard + imports + local DB
  -> validate full 0x addresses
  -> reject truncated addresses
  -> filter sample/history/drawdown/concentration
  -> write shortlist JSON

Job B - Copy loop dry-run every 300s
  shortlist
  -> /info positions + fills + openOrders
  -> optional read-only WS for shortlist only
  -> snapshot diff
  -> delta detector
  -> SignalCandidate
  -> edge_remaining_bps
  -> no_trade_report or paper intent

Job C - Reports every 30m / dashboard
  read-only state
  -> leader activity
  -> paper portfolio mock USDC
  -> refused signals
  -> copy status
  -> no_trade_report
```

## Job A - Smart Leaderboard + Auto-Select

Objectif: trouver des wallets interessants sans les inventer.

Sources:

- leaderboard Hyperliquid comme source prioritaire;
- explorer public comme source d'activite, mais jamais comme source de verite
  si l'adresse est tronquee;
- imports CSV/JSON/TXT;
- DB locale;
- fills deja collectes.

Filtres minimum:

- adresse complete seulement: `0x` + 40 hex, longueur 42;
- pas de `...`;
- minimum history days: 7;
- minimum closed PnL points;
- score de consistance;
- drawdown max;
- ROI/PnL par coin, sans inventer les valeurs;
- execution quality: maker/taker, fees, slippage estime, ordre ouvert vs fill;
- sample confidence;
- copyability;
- PnL concentration.

Regle PnL concentration:

- refuser un wallet dont l'essentiel du PnL vient d'un seul gros trade;
- penaliser les wallets mono-coin si l'edge parait non robuste;
- stocker la raison: `REJECTED_PNL_CONCENTRATION`.

Sortie:

- `leaderboard_shortlist.json`;
- `candidate_score`;
- `status`: `SHORTLISTED`, `REJECTED`, `INSUFFICIENT_DATA`, `WATCH_ONLY`;
- raison detaillee.

## Job B - Copy loop dry-run

Polling par defaut: 300 secondes.

Inputs:

- shortlist;
- snapshot precedent positions par wallet/coin;
- `clearinghouseState`;
- `userFillsByTime`;
- `userFills`;
- `openOrders`;
- `frontendOpenOrders`;
- optional WebSocket read-only pour shortlist.

Sorties:

- `LeaderDelta`;
- `SignalCandidate`;
- `NoTradeDecision`;
- paper intent local si toutes les gates passent.

Important: openOrders ne prouve pas un trade execute. Un ordre ouvert est un
contexte, pas une entree realisee.

## Delta detector

Classification par signed size:

| Ancien size | Nouveau size | Classification |
|---:|---:|---|
| 0 | >0 | `OPEN_LONG` |
| 0 | <0 | `OPEN_SHORT` |
| >0 | plus grand positif | `INCREASE` / `ADD` |
| <0 | plus negatif | `INCREASE` / `ADD` |
| >0 | plus petit positif | `REDUCE` |
| <0 | moins negatif | `REDUCE` |
| >0 | 0 | `CLOSE_LONG` |
| <0 | 0 | `CLOSE_SHORT` |
| >0 | <0 | `UNKNOWN` ou `FLIP_LONG_TO_SHORT` si modele futur |
| <0 | >0 | `UNKNOWN` ou `FLIP_SHORT_TO_LONG` si modele futur |

Classification par fill:

- `dir = Open Long` -> `OPEN_LONG` ou `ADD` selon `startPosition`;
- `dir = Open Short` -> `OPEN_SHORT` ou `ADD`;
- `dir = Close Long` -> `REDUCE` ou `CLOSE_LONG`;
- `dir = Close Short` -> `REDUCE` ou `CLOSE_SHORT`;
- `closedPnl` utile pour outcomes et score, pas pour garantir le futur.

Si les donnees se contredisent:

- `UNKNOWN`;
- warning;
- pas de candidate paper.

## SignalCandidate minimal

Champs recommandes:

- `candidate_id`;
- `leader_wallet`;
- `coin`;
- `action_type`;
- `observed_at`;
- `leader_fill_time`;
- `leader_reference_price`;
- `current_mid`;
- `spread_bps`;
- `slippage_bps`;
- `fee_bps`;
- `latency_ms`;
- `liquidity_score`;
- `leader_score`;
- `signal_freshness_score`;
- `copy_degradation_bps`;
- `edge_remaining_bps`;
- `paper_mode = PAPER_MOCK_USDC`;
- `decision = ACCEPT_PAPER | REJECT_NO_TRADE`;
- `refusal_reasons`;
- `raw_event_hash`.

## Edge remaining obligatoire

Le signal ne peut jamais etre accepte si `edge_remaining_bps` est absent,
negatif ou inferieur au seuil configure.

Formule de depart:

```text
edge_remaining_bps =
  leader_expected_edge_bps
  * leader_consistency_factor
  * signal_freshness_factor
  - delay_cost_bps
  - spread_bps
  - slippage_bps
  - fee_bps
  - liquidity_penalty_bps
  - adverse_selection_penalty_bps
  - crowding_penalty_bps
  - funding_penalty_bps
```

Par defaut, si `leader_expected_edge_bps` n'est pas mesurable:

- refuser;
- no-trade reason: `EDGE_UNMEASURABLE`.

Si le signal est vieux:

- refuser;
- no-trade reason: `STALE_SIGNAL`.

Si le carnet est trop mince:

- refuser;
- no-trade reason: `LIQUIDITY_TOO_LOW`.

## Copy degradation

Les repos et guides convergent: le copy trading se degrade entre le fill du
leader et notre simulation. Les couts a imposer:

- retard de polling ou WS;
- spread courant;
- slippage pessimiste;
- fees;
- profondeur carnet;
- notional trop gros;
- token trop illiquide;
- open interest / cap;
- crowding: plusieurs copybots suivent le meme wallet;
- action deja partiellement jouee;
- fill leader maker mais copy taker.

Le paper engine doit etre volontairement defavorable.

## Position sizing en paper

Patterns observes:

- sizing proportionnel au ratio equity follower/leader;
- sizing fixe en USDC;
- cap de notionnel par position;
- cap exposition totale;
- minimum notional;
- leverage clamp;
- blocked assets;
- max open positions;
- skip si deviation prix depuis entree leader trop grande.

Version HyperSmart Batch 1:

- paper mock USDC uniquement;
- notional faible par defaut;
- pas de leverage reel;
- pas de testnet executor;
- aucune signature;
- aucune API de trading.

## no_trade_report

Chaque refus doit etre visible. Raisons minimum:

- `TRUNCATED_ADDRESS_REJECTED`;
- `INVALID_ADDRESS_REJECTED`;
- `INSUFFICIENT_HISTORY`;
- `INSUFFICIENT_CLOSED_PNL`;
- `PNL_CONCENTRATION_TOO_HIGH`;
- `ONE_BIG_WIN_RISK`;
- `LOW_CONSISTENCY`;
- `MAX_DRAWDOWN_TOO_HIGH`;
- `STALE_SIGNAL`;
- `EDGE_UNMEASURABLE`;
- `EDGE_REMAINING_TOO_LOW`;
- `SPREAD_TOO_WIDE`;
- `SLIPPAGE_TOO_HIGH`;
- `LIQUIDITY_TOO_LOW`;
- `COPY_DEGRADATION_TOO_HIGH`;
- `UNKNOWN_DELTA`;
- `REDUCE_OR_CLOSE_NOT_ENTRY`;
- `NO_MATCHING_PAPER_POSITION_FOR_CLOSE`;
- `DUPLICATE_FILL`;
- `BLOCKED_ASSET`;
- `MAX_OPEN_PAPER_TRADES_REACHED`;
- `NETWORK_READ_DISABLED`;
- `SOURCE_UNAVAILABLE`;
- `RATE_LIMIT_GUARD`.

Le rapport doit expliquer en francais simple:

- ce qui a ete observe;
- pourquoi ce n'est pas simulable;
- quelle donnee manque;
- quelle action suivante est recommandee.

## Dashboard attendu

Sections read-only:

- Copy status;
- Top wallets followed;
- Leaderboard shortlist;
- Leader activity;
- Latest deltas;
- Signal candidates;
- No-trade report;
- Paper mock USDC portfolio;
- Edge remaining;
- Copy degradation;
- Source failures;
- Safety audit.

Interactions autorisees:

- filtrer;
- trier;
- rechercher;
- exporter un rapport;
- ouvrir les details techniques.

Interactions interdites:

- trade;
- order;
- execute;
- connect wallet;
- private key;
- mainnet;
- `/exchange`;
- signature.

## Ce que les repos apportent vraiment

### MaxIsOntoSomething/Hyperliquid_Copy_Trader

Elements utiles:

- monitor WebSocket;
- snapshot initial;
- callbacks new position / update / close;
- sizing proportionnel;
- caps de position;
- max open trades;
- blocked assets;
- deviation prix entree leader vs prix courant;
- simulated mode;
- SQLite possible.

Elements rejetes:

- private key;
- executor;
- market/limit order;
- Telegram control pouvant piloter l'execution.

### Dwellir copy-trading examples

Elements utiles:

- stream de fills;
- dry-run actif par defaut;
- duplicate guard;
- min/max notional;
- max positions;
- sync de la position follower avant fermeture;
- skip si aucune position locale a fermer.

Elements rejetes:

- ordre IOC;
- exchange SDK execution;
- credentials execution.

### Chainstack guide

Elements utiles:

- WebSocket `orderUpdates` + `userEvents`;
- state management;
- event sequencing;
- dynamic sizing;
- precision assets.

Elements rejetes:

- ordre via SDK;
- cle privee;
- production execution.

### PerpLobster

Elements utiles:

- dashboard web;
- SQLite metrics;
- configs lisibles;
- emergency stop comme concept d'UX;
- monitoring et risk controls.

Elements rejetes:

- quick trades;
- bots qui placent des ordres;
- builder fee approval;
- scripts d'execution.

### zkOSAI

Elements utiles:

- exemple minimal de mirroring;
- fixed `COPY_VALUE`;
- leverage cap;
- avertissement que copy trading ne garantit rien.

Elements rejetes:

- besoin de private key;
- API wallet;
- creation directe d'ordres;
- promesses trop execution-first.

## Tests a garder / ajouter

Tests indispensables:

- aucune adresse tronquee candidate;
- aucune adresse tronquee en scan queue;
- leaderboard shortlist refuse one-big-win;
- delta detector open/add/reduce/close;
- delta ambigu -> `UNKNOWN`;
- `edge_remaining_bps` absent -> refus;
- edge insuffisant -> no-trade;
- stale signal -> no-trade;
- spread/slippage/liquidite mauvais -> no-trade;
- close/reduce sans position paper correspondante -> no-trade;
- no LLM in hot path;
- aucun `/exchange`;
- aucune signature;
- aucune cle privee;
- aucun bouton dangereux;
- testnet disabled by default;
- dashboard read-only.

## Backlog par batches

### Batch 1 - deja cible

- Smart Leaderboard + Auto-Select;
- Copy Signal Detector dry-run only;
- delta detection;
- `edge_remaining_bps`;
- no-trade report;
- dashboard copy status / leader activity / refused signals.

### Batch 2 - durcir les donnees

- `leaderboard_shortlist.json` versionne en `data/`;
- snapshots positions/fills/openOrders;
- resume cursors pour `userFillsByTime`;
- dedupe fill par `hash/tid/oid/time`;
- source health.

### Batch 3 - WebSocket shortlist

- read-only WebSocket;
- max 10 users uniques;
- duration limitee;
- fallback polling;
- heartbeat/reconnect/backoff;
- no infinite monitor.

### Batch 4 - replay/backtest copy

- reconstituer les deltas historiques;
- appliquer retard 5min / 60s / WS;
- fees/spread/slippage/latence;
- missed fills;
- paper equity curve;
- no-trade report retrospectif.

### Batch 5 - paper portfolio UX

- paper mock USDC dashboard;
- PnL paper net;
- drawdown paper;
- refused vs accepted;
- source failures;
- export HTML/CSV.

### Batch 6 - testnet futur, verrouille

Hors scope actuel. Seulement apres validation explicite:

- `--confirm-testnet-only`;
- mock USDC;
- cloid deterministe;
- duplicate guard;
- scheduleCancel;
- no mainnet.

## Position finale de recherche

Le meilleur "clone" de ce bot pour HyperSmart n'est pas un executor. C'est un
observateur qui prouve:

- quels wallets sont suivis;
- pourquoi ils sont suivis;
- quelles ouvertures/fermetures sont detectees;
- quelles simulations paper seraient autorisees;
- quelles simulations sont refusees;
- combien d'edge reste apres couts;
- combien le copy trading se degrade avec le retard;
- quand il faut ne rien faire.

La valeur n'est pas dans une promesse. Elle est dans la mesure, le refus et la
trace.

## Implementation mapping

Les batches sont relies au code local suivant:

- Batch 1: `hyper_smart_observer/copy_mode/leaderboard_selector.py`,
  `delta_detector.py`, `signal_candidate.py`, `edge.py`,
  `no_trade_report.py`.
- Batch 2: `data/leaderboard_shortlist.json`, tables
  `leaderboard_shortlist`, `leader_snapshots`, `fill_dedupe`,
  `copy_signal_candidates`, `no_trade_decisions`, `source_health`.
- Batch 3: `hyper_smart_observer/realtime_monitor/`, commande
  `copy-run --ws --duration-seconds N --dry-run`.
- Batch 4: `hyper_smart_observer/backtesting/` et commandes
  `--backtest-wallet`, `--backtest-top-wallets`.
- Batch 5: `hyper_smart_observer/dashboard/exporter.py` avec sections copy
  status, shortlist, signal candidates, no-trade, edge remaining et copy
  degradation.
- Batch 6: `promote-testnet-candidates --dry-run` reste verrouille et
  n'active aucun executor.
## 2026-05-26 Research Digest Addendum

Detailed public-source findings and their safe HyperSmart translation are now
tracked in `docs/HYPERSMART_MAGIC_BOT_RESEARCH_DIGEST.md`.

New implemented item from the research pass:

- `hyper_smart_observer/copy_mode/sizing.py` implements local paper mock USDC
  proportional sizing from leader/follower equity ratio, with min notional,
  max notional cap, blocked asset refusal, and missing-data refusal.

Still not implemented by design:

- no `/exchange`;
- no signature;
- no private key;
- no live order;
- no active testnet executor;
- no mainnet.

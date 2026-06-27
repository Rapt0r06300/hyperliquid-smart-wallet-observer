# HyperSmart V9 - Execution Status

Date: 2026-06-19

## Source appliquee

- Feuille de route: `docs/HYPERSMART_FUSION_ROADMAP_V9.md`
- Regles locales: `AGENTS.md`

Decision d'architecture appliquee:

- Runtime officiel: Hyperliquid-first, simulation locale uniquement, read-only.
- Modules `hyper_smart_observer/dydx_v4/`: conserves comme legacy/mockable, non montes dans l'UI Hyperliquid par defaut.
- Les idees V9 issues de dYdX/GitHub doivent etre fusionnees vers Hyperliquid quand elles ameliorent la simulation sans execution reelle.

## Tranche livree

### S0 - Runtime mode et contextes de PnL

Etat: tranche livree et testee.

Correctif reel livre:

- Nouveau module `src/hl_observer/runtime_mode.py`.
- Nouveau module `src/hl_observer/storage/run_context.py`.
- Nouveau module `src/hl_observer/config/defaults.py`.

Garanties ajoutees:

- Mode runtime nomme `PAPER`.
- Testnet force en `TESTNET_LOCKED`, non executable.
- Execution, ordres, signatures et wallet connect toujours `False`.
- Defaults deny-by-default:
  - network read off par defaut;
  - dry-run on par defaut;
  - mainnet/testnet execution off;
  - fake data/fake PnL off;
  - retries/max_api_errors bornes.
- Contextes `LIVE`, `BACKTEST`, `REPLAY`, `TEST_FIXTURE`.
- Le PnL paper ne peut etre fusionne que si le contexte et `paper_session_id` correspondent.

Tests:

```powershell
python -m pytest -q tests/test_v9_runtime_mode_and_run_context.py
```

Resultat: `7 passed`.

### S1 - Modeles communs et normalisation

Etat: tranche de base livree et testee.

Correctif reel livre:

- Nouveau package `src/hl_observer/models/`.
- Nouveau package `src/hl_observer/normalization/`.

Capacites ajoutees:

- Modeles Pydantic:
  - `Wallet`;
  - `Coin`;
  - `Position`;
  - `OpenOrder`;
  - `Fill`;
  - `Candle`;
  - `BookLevel`;
  - `SourceMeta`;
  - `NormalizedDelta`.
- Rejet des adresses tronquees ou invalides.
- Classification position:
  - `OPEN_LONG`;
  - `OPEN_SHORT`;
  - `INCREASE`;
  - `REDUCE`;
  - `CLOSE_LONG`;
  - `CLOSE_SHORT`;
  - `UNKNOWN`.
- Flip long/short ou short/long => `UNKNOWN` + pas de paper intent.
- Classification fill prudente:
  - close sans position resultante connue => `UNKNOWN`;
  - donnees insuffisantes => pas de paper intent.
- Reconciliation REST/WS:
  - divergence taille position => `RECONCILIATION_DIVERGENCE_NO_TRADE`;
  - source manquante => `RECONCILIATION_SOURCE_MISSING_NO_TRADE`.
- Inference de fill depuis polling position:
  - basse confiance;
  - jamais preuve forte;
  - prix reel requis.

Tests:

```powershell
python -m pytest -q tests/test_v9_common_models_and_normalization.py
```

Resultat: `6 passed`.

### S0 - Fondations et garde-fous

Etat: partiellement renforce.

Correctif reel livre:

- Le poller `tools/hypersmart_simulation_poll_loop.ps1` ne peut plus s'arreter immediatement si `MaxRuns=0` arrive depuis un appel externe ou un ancien lanceur.
- Le lanceur `tools/start_hypersmart_simulation.ps1` ecrit un heartbeat `launcher_starting` avant le demarrage de l'UI et du poller. La page ne doit plus heriter d'un ancien `finished` comme etat initial trompeur.
- Le lanceur passe explicitement `-MaxRuns 5760` au poller.

Cause racine observee dans les logs:

```text
Simulation poll loop started ... maxRuns=0
Simulation poll loop finished.
```

Effet utilisateur:

- L'UI pouvait afficher `Demarrage du moteur...`, `0 wallets`, `WS OFF`, ou rester sans scan, alors que le poller avait deja termine.
- Le navigateur pouvait ensuite afficher une page locale inaccessible si le serveur UI avait ete arrete avec le lanceur.

### S2bis - Budget de donnees fraiches Hyperliquid

Etat: tranche livree et testee, etendue avec sharding egress read-only.

Correctif reel livre:

- Nouveau module `src/hl_observer/collection/weight_budgeter.py`.
- Nouveau module `src/hl_observer/collection/proxy_pool.py`.
- Nouveau module `src/hl_observer/collection/backoff.py`.
- Nouveau module `src/hl_observer/collection/circuit_breaker.py`.
- Nouveau module `src/hl_observer/collection/rate_limiter.py`.
- Nouveau module `src/hl_observer/collection/html_scraper.py`.
- Nouvelle commande CLI `collection-budget-plan`.
- Le moteur possede maintenant un contrat auditable avant collecte:
  - estimation conservative du poids REST;
  - marge sure par defaut a 70% de 1200 poids/minute;
  - prise en compte `allMids`, appels `/info` legers, appels `/info` par defaut, explorer public et endpoints temporels;
  - caps WebSocket: 10 connexions, 30 nouvelles connexions/minute, 1000 subscriptions, 10 users uniques, 2000 messages/minute;
  - refus explicite si `--network-read` absent;
  - refus explicite de bypass/aggressive scraping;
  - refus explicite si le batch depasse le budget ou les caps WS;
  - execution toujours `forbidden`.

But produit:

- Quand la simulation dit `signal trop vieux`, `edge degrade`, `0 wallet`, ou `WS OFF`, on peut maintenant auditer si le prochain cycle est bloque par le budget, par le reseau non autorise, par un cap WebSocket, ou par un batch trop lourd.
- Cette brique permet d'augmenter la fraicheur par rotation, streams publics,
  cache local et budget par egress, sans inventer de donnees et sans execution
  argent-reel.
- `proxy_pool.py` implemente un planificateur de shards/cooldowns, pas un client reseau:
  - sticky-by-shard;
  - budget agrege auditable;
  - endpoint en cooldown sur 429/403/timeout;
  - redaction des credentials;
  - refus d'une finalite `bypass` non auditable;
  - execution toujours `forbidden`.
- `backoff.py` respecte `Retry-After`, borne les delais et ajoute un jitter deterministe.
- `circuit_breaker.py` ouvre/ferme/half-open par egress/source.
- `rate_limiter.py` applique une fenetre glissante type 25 requetes / 10 s.
- `html_scraper.py` extrait uniquement les adresses completes publiques et retourne un etat vide honnete si la page ne contient rien.

Commande utile:

```powershell
python -m hl_observer.cli collection-budget-plan --network-read --all-mids-calls 1 --default-info-calls 3 --time-range-items 40 --ws-unique-users 10
```

Sortie attendue:

- `collection_budget=hyperliquid_read_only`
- `allowed=true`
- `read_only=true`
- `execution=forbidden`

### S3 - WebSocket supervisor read-only

Etat: tranche livree et testee.

Correctif reel livre:

- Nouveau module `src/hl_observer/realtime_monitor/ws_supervisor.py`.
- Export public dans `src/hl_observer/realtime_monitor/__init__.py`.

Capacites ajoutees:

- Plan de subscriptions read-only.
- Cap de 10 users uniques user-specific.
- Cap de 1000 subscriptions.
- Cap de 2000 messages/minute.
- Cap de 30 nouvelles connexions/minute.
- Fallback REST explicite si un cap est depasse.
- Deduplication des snapshots `isSnapshot` au niveau des items, pas seulement du payload entier.
- Snapshot mixte accepte seulement s'il contient au moins un nouvel item.
- Heartbeat stale => `HEARTBEAT_STALE_REST_GAP_RECOVERY`.
- Backoff reconnect borne et reset apres message accepte.
- Execution toujours `forbidden`.

Tests:

```powershell
python -m pytest -q tests/test_v9_ws_supervisor.py
```

Resultat: `6 passed`.

### S4 - Features marche Hyperliquid officielles

Etat: tranche livree et testee.

Correctif reel livre:

- Nouveau package `src/hl_observer/features/`.
- Nouveau module `src/hl_observer/features/market.py`.

Capacites ajoutees:

- Derivation du mid avec provenance:
  - `MID_FROM_BOOK`;
  - `MID_FROM_ALL_MIDS`;
  - `MID_FROM_LAST_TRADE_FALLBACK`;
  - `MID_MISSING`.
- Features l2Book:
  - best bid/ask;
  - spread bps;
  - profondeur bid/ask en USDC;
  - microprice;
  - imbalance;
  - depth slope;
  - liquidity score.
- Volatilite depuis candles reelles:
  - range bps;
  - realized vol bps;
  - ATR bps;
  - bucket `LOW/NORMAL/HIGH/EXTREME`.
- `MarketFeatureVector` exportable avec `feature_hash`.
- `MarketQualityDecision`:
  - `TRADEABLE` si les features sont propres;
  - `NO_TRADE` avec raisons explicites sinon.
- Aucun reseau, aucune donnee inventee, aucun PnL fabrique.

Tests:

```powershell
python -m pytest -q tests/test_v9_market_features_src.py
```

Resultat: `5 passed`.

### S5 - Evidence chain et pipeline paper local

Etat: tranche livree et testee.

Correctif reel livre:

- Nouveau package `src/hl_observer/ledger/`.
- Nouveau module `src/hl_observer/ledger/evidence.py`.
- Nouveau module `src/hl_observer/copying/simulation_pipeline.py`.
- Export public dans `src/hl_observer/copying/__init__.py`.

Capacites ajoutees:

- `EvidenceChainEntry` append-only:
  - signal;
  - feature hash marche;
  - risk decision;
  - paper order simule;
  - reasons;
  - source refs;
  - evidence hash reproductible.
- Export JSON/CSV `evidence_chain_<run>.json/csv`.
- Reconstruction par `decision_id`.
- Pipeline officiel:
  - `SignalCandidate`;
  - `MarketFeatureVector`;
  - `RiskEngine`;
  - `PaperExecutor`;
  - `EvidenceChainEntry`.
- Ajustement de l'edge par `min_edge_bps_addon` issu des features marche.
- Marche stale/thin/wide => no-trade, pas de notional paper positif.
- Simulation locale uniquement; aucun ordre reel.

Tests:

```powershell
python -m pytest -q tests/test_v9_evidence_chain_src.py tests/test_v9_simulation_pipeline_src.py
```

Resultat: `7 passed`.

### S6 - Parite runtime paper / replay paper

Etat: tranche livree et testee.

Correctif reel livre:

- Nouveau module `src/hl_observer/backtest/runtime_parity.py`.
- Export public dans `src/hl_observer/backtest/__init__.py`.

Capacites ajoutees:

- Comparaison deterministe entre:
  - decision paper live;
  - decision paper replay.
- Les memes inputs read-only produisent:
  - meme risk decision;
  - meme notional paper;
  - meme fill paper pessimiste;
  - memes frais/slippage;
  - meme rejet si no-trade.
- Les contextes `LIVE` et `REPLAY` restent separes:
  - PnL non fusionnable;
  - evidence hash differente car `run_id` different;
  - economie paper comparable sans melanger l'historique.

Tests:

```powershell
python -m pytest -q tests/test_v9_runtime_replay_parity_src.py
```

Resultat: `2 passed`.

## Tests executes

```powershell
python -m pytest -q tests/test_hypersmart_single_launcher.py
python -m pytest -q tests/test_ui_simulation_status_fast.py
python -m pytest -q tests/test_hyperliquid_runtime_does_not_import_dydx_by_default.py
python -m pytest -q tests/test_dydx_is_secondary_mockable_not_runtime.py
python -m pytest -q tests/test_hypersmart_v9_collection_budget.py
python -m pytest -q tests/test_v9_proxy_pool_safe_sharding.py
python -m pytest -q tests/test_v9_collection_resilience_and_html.py
python -m pytest -q tests/test_v9_ws_supervisor.py
python -m pytest -q tests/test_v9_market_features_src.py
python -m pytest -q tests/test_v9_evidence_chain_src.py
python -m pytest -q tests/test_v9_simulation_pipeline_src.py
python -m pytest -q tests/test_v9_runtime_replay_parity_src.py
python -m pytest -q tests/test_copy_cli_and_safety.py
python -m pytest -q tests/test_hypersmart_api_limits_constants.py
```

Resultat:

- `tests/test_hypersmart_single_launcher.py`: 5 passed
- `tests/test_ui_simulation_status_fast.py`: 10 passed
- `tests/test_hyperliquid_runtime_does_not_import_dydx_by_default.py`: 1 passed
- `tests/test_dydx_is_secondary_mockable_not_runtime.py`: 3 passed
- `tests/test_hypersmart_v9_collection_budget.py`: 8 passed
- `tests/test_v9_proxy_pool_safe_sharding.py`: 6 passed
- `tests/test_v9_collection_resilience_and_html.py`: 6 passed
- `tests/test_v9_ws_supervisor.py`: 6 passed
- `tests/test_v9_market_features_src.py`: 5 passed
- `tests/test_v9_evidence_chain_src.py`: 3 passed
- `tests/test_v9_simulation_pipeline_src.py`: 4 passed
- `tests/test_v9_runtime_replay_parity_src.py`: 2 passed
- `tests/test_copy_cli_and_safety.py`: 18 passed
- `tests/test_hypersmart_api_limits_constants.py`: 2 passed

Dernier run consolide V9:

```powershell
python -m pytest -q tests/test_v9_runtime_mode_and_run_context.py tests/test_v9_common_models_and_normalization.py tests/test_hypersmart_v9_collection_budget.py tests/test_v9_proxy_pool_safe_sharding.py tests/test_v9_collection_resilience_and_html.py tests/test_v9_ws_supervisor.py tests/test_v9_market_features_src.py tests/test_v9_evidence_chain_src.py tests/test_v9_simulation_pipeline_src.py tests/test_v9_runtime_replay_parity_src.py
```

Resultat: `54 passed`.

Verification PowerShell:

```powershell
[scriptblock]::Create((Get-Content -Raw 'tools/start_hypersmart_simulation.ps1'))
[scriptblock]::Create((Get-Content -Raw 'tools/hypersmart_simulation_poll_loop.ps1'))
```

Resultat:

- `start_script_parse_ok`
- `poll_loop_parse_ok`

## Ce qui n'a pas ete pretendu termine

V9 n'est pas entierement terminee.

Restent notamment:

- audit complet S1/S2/S3 sur normalisation, snapshots, REST/WS et dedupe;
- branchement de l'evidence_chain officielle dans tous les chemins UI/poller existants;
- QA longue duree du WebSocket read-only;
- dashboard des causes de non-demarrage et des refus frais;
- rapport de couverture V9 ligne par ligne.
- branchement du nouveau budgeteur dans tous les points d'entree live, pas seulement en commande d'audit.

## Prochaine priorite exacte

1. Brancher `collection-budget-plan` / `weight_budgeter` directement dans:
   - `fresh-data-plan`;
   - `fresh-scan-plan`;
   - `copy-run --network-read`;
   - le poller simulation.
2. Ajouter un test d'integration court qui lance le poller avec `-MaxRuns 0` sur commandes fake/mockees, et verifie qu'il applique le garde-fou sans ecrire `finished` immediat.
3. Brancher dans le dashboard un indicateur lisible:
   - serveur UI actif;
   - poller actif;
   - age heartbeat;
   - phase courante;
   - derniere erreur poller;
   - prochain scan attendu.
4. Auditer la chaine:
   `live-public-scan -> live-user-fills-scan -> copy-run -> opportunity-report -> paper entry/NO_TRADE`
   pour expliquer pourquoi `fresh_entry_deltas` diverge entre readiness et warehouse.

## Garde-fous confirmes

- Aucun ordre reel.
- Aucun mainnet.
- Aucun `/exchange` operationnel.
- Aucune signature.
- Aucune cle privee.
- Simulation locale uniquement.
- dYdX conserve comme legacy/mockable, non lance par defaut.

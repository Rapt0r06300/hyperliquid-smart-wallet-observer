# HyperSmart Observer — Agent Rules

## Mission
HyperSmart Observer observe **Hyperliquid** en lecture seule, score les wallets smart-money et le marché, et **simule des décisions paper en local**. Il ne doit **jamais** envoyer d'ordre réel. But : produire un PnL paper réaliste, proche de ce qu'on aurait eu en vrai sur Hyperliquid — sans jamais le maquiller ni le promettre.

## Venue & Runtime (IMPORTANT — ne pas confondre)
- **Venue = Hyperliquid uniquement.** Simulation paper locale, read-only.
- **Runtime ACTIF de la simulation = `src/hl_observer`.** Lancé par `LANCER_HYPERSMART.cmd` → `tools/start_hypersmart_simulation.ps1` → `python -m hl_observer ui` (port 8794, `PYTHONPATH=src`).
  - Collecte Hyperliquid : `hyperliquid/` (`/info`), `collection/`, `realtime/` (WS public).
  - Moteur d'edge : `src/hl_observer/edge/edge_calculator.py` (`compute_net_edge`, plancher net par défaut 30 bps).
  - PnL / exits : `src/hl_observer/paper_trading/` (marqué `FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID`, `sltp_runtime.py`).
  - Plancher profit-USD **déjà présent** : env `HYPERSMART_SIMULATION_MIN_EXPECTED_EDGE_USDT` → reason `EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS`.
- **`hyper_smart_observer/dydx_v4/` = vrai dYdX LEGACY** — sa config pointe `indexer.dydx.trade`. Ce **n'est PAS** la simulation Hyperliquid. `ui/dydx_routes.py` = panneau secondaire dYdX. **Ne jamais y porter d'idées destinées à la simu.**
- **`hyper_smart_observer/` (hors dydx_v4)** = legacy/compat isolé. Ne pas étendre.
- **Toute nouvelle intégration (copy / arbitrage / funding) vise `src/hl_observer/`** (`edge/`, `paper_trading/`, `signals/`, `risk/`, `arbitrage/`, `funding/`), jamais `dydx_v4`.

## Sécurité non négociable
- Aucun ordre réel, aucun `/exchange` réel, aucune clé privée, aucune signature réelle, aucun wallet connect pour agir, aucun endpoint d'exécution activé.
- Les mots trading (trade, order, buy, sell, exchange, signature, hedge, arbitrage, PaperIntent, MockExchange…) sont **autorisés** en tests/mocks/paper/sim/backtest/audit/doc/dashboard. Seule l'**action réelle** est interdite.
- L'audit sécurité distingue un **mot** (test/mock/doc) d'un **vrai appel** opérationnel dangereux.
- `PaperIntent` / `PaperTrade` ne sont pas des ordres.

## Vérité des données (règle dure)
- **Aucune donnée fabriquée, aucune démo présentée comme réelle.** Données réelles Hyperliquid ou **état vide honnête**.
- Donnée manquante / trop vieille / contradictoire / incomplète → `INSUFFICIENT_DATA` ou `NO_TRADE`.
- Ne jamais inventer PnL, wallets, fills, positions, ni mouvement de courbe.

## Vérité du PnL paper
- Le PnL vient d'un **ledger d'événements**, pas d'un compteur fragile.
- Composants : cash, positions ouvertes/fermées, prix entrée/sortie, realized, unrealized, equity, drawdown, fees, funding, spread, slippage, latence, partial/missed fills, liquidation, exits.
- **Dashboard, audit, logs, exports convergent sur le même ledger.** Si le dashboard montre une perte, l'audit doit l'expliquer (trade, signal, wallet, coin, prix, coûts, funding, latence, exit, cause).

## But quant
Moins de trades, beaucoup plus propres. Filtrer les mauvais signaux ; ne garder que les signaux frais, cohérents, liquides, à **edge net positif après** frais + spread + slippage + latence + dégradation de copie. Juger au **profit factor**, pas au winrate brut. Jamais de promesse de PnL.

## Règles d'ingénierie
- Ne rien supprimer brutalement (dossiers, logs, données, tests, configs, simulation, scripts de lancement).
- Pas de module isolé sans test **et** plan de câblage.
- Préférer de petits modules importables sous `src/hl_observer`.
- Ne pas éditer via Write/bash les très gros fichiers tronqués par le mount (`src/hl_observer/cli.py` ~3400 l., `ui/routes.py`) — ajouter via nouveaux petits modules importés.
- Renforcer l'existant plutôt que créer des doublons ; ne pas introduire de 3ᵉ architecture.

## Portage GitHub (repos dans `runtime/research/github_repos_v24/`)
- Ne pas copier en aveugle. Classer chaque idée : `COPY_DIRECT`, `COPY_ADAPTED`, `PORT_BEHAVIOR`, `INSPIRE_ONLY`, `SKIP_WITH_REASON`, `DEFERRED_WITH_PLAN`.
- Ne jamais prétendre avoir lu un fichier non lu, ni porté un comportement sans test/branchement le prouvant.
- Aucun repo externe ne bypasse le RiskEngine, le ledger, ou le no-real-trade.
- Toute idée retenue passe par DecisionEngine/RiskEngine → PaperIntent ou NO_TRADE → PaperLedger.

## Tests
Sous-ensemble ciblé (sandbox, `PYTHONPATH=src`) :
`python -m pytest -q tests/test_error_handler.py tests/test_circuit_breaker.py tests/test_retry_policy.py tests/test_state_manager.py tests/test_no_real_trade_foundations.py tests/test_paper_ledger.py tests/test_pnl_reconciliation.py tests/test_orderbook_execution_simulator.py tests/test_simulation_realism_audit.py`

Vérité complète (sur Windows, gros fichiers non tronqués) :
`set PYTHONPATH=src && python -m pytest -q`

Sécurité (runtime Hyperliquid) :
`python -m hl_observer doctor` · `python -m hl_observer safety-audit` · `python -m hl_observer audit-safety`

## Definition of Done
Une feature est DONE seulement si : codée, testée, documentée, câblée (ou marquée `PARTIAL_NOT_WIRED`), et sans affaiblir le no-real-trade. Un rapport sans code n'est accepté que pour une étape d'analyse. Une simulation qui ignore fees/slippage/funding, ou un dashboard dont le PnL diverge de l'audit, n'est pas DONE.

## Addendum 2026-07-04 — bascule vers testnet contrôlé
Le cap produit change : la simulation paper complète ne doit plus être le coeur du système. Elle reste en legacy/minimal guardrail pour tester les décisions, les coûts et les refus, mais le chemin cible devient :

1. `mainnet_readonly_observer` lit Hyperliquid mainnet uniquement en lecture seule : vrais prix, carnets, wallets, fills publics, signaux et santé des sources.
2. `decision_engine` décide localement, explique chaque décision, écrit une evidence chain et refuse si la donnée est trop vieille, contradictoire, insuffisante ou trop coûteuse.
3. `testnet_executor` peut envoyer une action uniquement vers un environnement testnet à fausse monnaie, jamais vers mainnet.

Contraintes obligatoires pour le testnet :
- `REAL_MAINNET_TRADING=false`.
- `TESTNET_ONLY=true`.
- `CONFIRM_TESTNET_EXECUTION=true` pour toute action externe testnet.
- `MAX_TESTNET_NOTIONAL` et `MAX_OPEN_TESTNET_POSITIONS` doivent limiter le risque testnet.
- L'interface officielle à utiliser est `TestnetExchangeAdapter`, avec un fake adapter obligatoire pour les tests.
- Par défaut, aucun secret, aucune clé privée et aucune signature réelle ne sont utilisés. Une vraie signature testnet ne pourra être ajoutée que dans un futur sprint explicite, isolé et audité.
- Tout adaptateur doit refuser si l'environnement n'est pas explicitement testnet.
- Tout ordre mainnet reste impossible.

Le dashboard doit distinguer clairement :
- observation mainnet read-only ;
- décision locale ;
- simulation minimale legacy ;
- exécution testnet verrouillée ;
- PnL testnet, avec l'avertissement que la liquidité testnet peut diverger du mainnet.

La prochaine architecture à privilégier est donc :
`mainnet_readonly_observer -> decision_engine -> testnet_executor -> journal/dashboard/audit`.

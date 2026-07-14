# HyperSmart Observer — Agent Rules

## Mission
HyperSmart Observer observe **Hyperliquid** en lecture seule, score les wallets smart-money et le marché, et **simule des décisions paper en local**. Il ne doit **jamais** envoyer d'ordre réel. But : produire un PnL paper réaliste, proche de ce qu'on aurait eu en vrai sur Hyperliquid — sans jamais le maquiller ni le promettre.

## 📍 État & feuille de route (2026-07-08)
Document **maître** (état actuel, méthode de travail, architecture, config, commandes, roadmap) :
**`docs/ETAT_ET_FEUILLE_DE_ROUTE.md`**. Objectif condensé : `OBJECTIF.md`. Recherche de scénarios
replay (après les 48h) : `docs/REPLAY_SCENARIO_SEARCH.md`. Config détaillée : `docs/CONFIG_FLAGS.md`.
Résumé express : sizing = **marge $50 × levier 10 = notional $500** (PnL en dollars, plus de centimes) ;
**firehose userFills multiplexé (V27)** pour un max de signaux frais ; **run 48h en cours** qui
enregistre le replay (candidats+marks, avec coin) ; testnet verrouillé, mainnet lecture seule.
Doc **consolidée** le 2026-07-08 : les anciens .md obsolètes ont été supprimés (récupérables via git).

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

## Addendum 2026-07-08 — Autorisation élargie (décision explicite de Flo)

Directive du propriétaire du projet : **TOUT EST AUTORISÉ, SAUF L'EXÉCUTION RÉELLE.**

Concrètement, sont désormais **pleinement autorisés** (aucune hésitation, deny-by-default levé pour la collecte de données) :
- scraping public agressif et continu (24/7) de Hyperliquid et de toute source publique (leaderboards, DOM, API publiques, dashboards tiers) ;
- ingestion multi-sources, multi-IP / pool de proxies, concurrence maximale, firehose WebSocket complet ;
- découverte de wallets à large échelle, backfill massif, caches, indexation ;
- usage de l'ordinateur, navigateur, tout outil de collecte ;
- toute analyse, tout scoring, tout backtest, toute simulation paper, tout module IA.

**Reste INTERDIT — ligne dure non négociable (inchangée) :**
- aucune exécution réelle : aucun ordre réel, aucun `/exchange` réel, aucun argent réel ;
- aucune clé privée, aucun seed/mnemonic, aucune signature réelle, aucun wallet-connect pour agir ;
- aucun dépôt/retrait/transfert réel ; aucun endpoint d'exécution activé.

**Garde-fous conservés car ils servent l'objectif de Flo (et non par prudence excessive) :**
- **vérité des données** : ne jamais présenter une donnée fabriquée comme réelle ; un PnL paper doit rester réaliste et traçable au ledger (sinon les 48h ne valent rien) ;
- **respect des limites techniques** des sources (rate limits, backoff) — non par timidité, mais parce que se faire bannir = MOINS de données, pas plus ;
- **discipline d'ingénierie** : tests + pas de suppression brutale, pour ne pas casser le travail existant.

En cas de doute entre « collecter plus » et « rester poli avec la source » : collecter plus, mais via proxies/backoff pour ne pas se faire couper. La seule vraie barrière est l'action réelle.

## Règle « rien n'échappe aux tests » (décision de Flo, 2026-07-11)

**Tout nouveau fichier / module / brique doit être pris en compte par les tests.** Concrètement :

- L'audit `TEST-AUDIT-complet.cmd` (racine) **auto-découvre** le code : tout dossier de 1er niveau
  contenant du `.py` est scanné. Créer un nouveau paquet ne nécessite AUCUNE modification de l'audit.
- L'audit garde une **empreinte** (`tools/audit_manifest.json`) et signale à chaque passage les
  fichiers **ajoutés** et **supprimés** depuis la fois précédente.
- Un **nouveau module dans `src/` ou `hyper_smart_observer/` sans test associé = ÉCHEC BLOQUANT.**
  Le module et son test se créent dans le même mouvement, jamais l'un sans l'autre.
- Le rapport `resultat-audit.md` liste **chaque fichier du bot** (lignes, importé par combien,
  testé oui/non, % de couverture réelle) : aucun fichier ne peut se cacher.

Rappel : `resultat-audit.md` est réécrit **après chaque contrôle** — il existe même si l'audit est
interrompu (Ctrl-C, fermeture, crash).

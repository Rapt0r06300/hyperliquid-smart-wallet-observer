# HyperSmart GitHub Rescan Codex

Date: 2026-06-17

Objectif: conserver et fusionner les meilleures idees observees dans les repos
externes, sans copier de code et sans importer de runtime dangereux. Tout est
adapte a Hyperliquid en lecture seule, simulation paper locale, et dashboard
read-only.

Sources verifiees par navigateur:

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
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket

## Decision generale

Les repos externes sont des bibliotheques d'idees. On ne supprime pas une idee
parce qu'elle semble "magique"; on la classe:

- KEEP si elle est directement utile et safe.
- ADAPT_HL si elle vient d'une autre venue mais peut etre transformee vers
  Hyperliquid `/info` ou WS read-only.
- DEFER si elle est utile plus tard mais trop lourde maintenant.
- BAN seulement si elle implique execution reelle, cle privee, signature, CLOB
  runtime, wallet connect, faux PnL, faux graphe, live toggle, ordre, ou promesse
  de profit.

## Matrice rescan

| Repo | Scope revu | Decision | Modules HyperSmart | Tests/preuves | Notes |
|---|---|---|---|---|---|
| CloddsBot | Agent trading multi-venues, dashboard, diagnostics, whale/copy tracking, ledger, Claude UI | ADAPT_HL | `dashboard`, `copy_mode`, `agent_tools`, `audit`, `logs/logs a envoyer` | `test_github_fusion_docs_exist.py`, `test_no_profit_promise_docs.py` | Garder l'idee de console riche, logs et diagnostics. BAN pour execution instantanee, paiement, credentials et agent hot path. |
| Harrier toolkits | Core execution/risk multi-strategies, adapters, circuit breakers | ADAPT_HL | `risk_engine`, `hyperliquid_client`, `realtime_monitor`, `copy_mode` | `test_no_exchange_sdk_imports_or_actions.py`, `test_copy_run_rate_limit_guard_shortlist.py` | Garder l'architecture adapter/risk/circuit breaker. Execution reelle BAN. |
| MrFadiAi Polymarket-bot | Strategies, scoring, sizing, dry-run/live split | ADAPT_HL | `scoring`, `copy_mode.signal_candidate`, `paper_trading` | `test_edge_remaining_threshold_no_trade.py`, `test_paper_intent_only_after_risk_engine.py` | Garder winrate, profit factor, consistency, one-big-win, pnl concentration. Private key/live toggle BAN. |
| polymarket_lp_tool | WS-first, REST reconcile, mid stability, cooldown, source health | ADAPT_HL | `realtime_monitor`, `copy_mode.snapshot_engine`, `market_signals` | `test_hypersmart_ws_dedupe.py`, `test_no_open_orders_only_paper_intent.py` | Tres utile pour temps reel: WS comme source chaude, REST comme reconciliation. Toute logique d'ordre BAN. |
| PolyWeather | Dashboard autoritatif, stale blocking, health/status, event patches | KEEP/ADAPT_HL | `dashboard`, `ui.routes`, `runtime`, `source_health` | `test_dashboard_no_fake_paper_positions.py`, `test_no_fake_chart_or_fake_position_data.py` | Garder refresh event-driven et stale policy. Paiements/onchain checkout BAN. |
| Composio arbitrage bot | Health/status/current signal, scanner state, timing gates | ADAPT_HL | `app.main`, `ui.routes`, `no_trade_report` | `test_hypersmart_runtime_check.py`, `test_no_exchange_sdk_imports_or_actions.py` | Garder API status et raisons no-trade. CLOB/ethers/private key/trading enabled BAN. |
| Awesome Prediction Market Tools | Benchmark produits: analytics, leaders, copyability, alerts | KEEP | `wallet_discovery`, `dashboard`, `scoring` | `test_repo_idea_matrix_has_keep_adapt_ban_defer.py` | Sert de checklist UX produit. One-click copy/execution BAN. |
| PolyTerm | TUI, manifests, JSON schemas, doctor, exports, zero custody | KEEP | `agent_tools`, `dashboard.exporter`, `runtime` | `test_agent_safe_manifest_readonly_only.py` | Tres utile pour outils ChatGPT/Jules: lire/exporter/diagnostiquer sans ecrire de trade. |
| mlmodelpoly | WS, OHLCV, CVD, VWAP, volatility, fair value, edge, logs JSON | ADAPT_HL | `market_signals`, `edge`, `logs/logs a envoyer` | `test_volatility_context_from_candles.py`, `test_decision_links_to_market_feature_hash.py` | Garder microstructure et feature rows. Binance/Polymarket runtime et secrets BAN. |
| polyrec | CSV riche, orderbook levels, imbalance, microprice, slope, backtesting | ADAPT_HL | `market_signals.orderbook_features`, `backtesting`, `dashboard` | `test_l2book_liquidity_score.py`, `test_dashboard_payload_shows_real_market_features.py` | Garder features explicables et exports. Hypotheses speciales BTC Polymarket DEFER. |
| prediction-market-backtesting | Replay, adapters, equity/drawdown, fees/slippage/latency | KEEP/ADAPT_HL | `backtesting.runtime_parity`, `paper_trading` | `test_backtest_runtime_parity_market_features_reason_codes.py` | Garder parite runtime/backtest pour comprendre pourquoi on perd. Execution live BAN. |
| polybot | Architecture ingestion/strategy/analytics/monitoring, scale | DEFER | `docs`, futur `pipeline` | `test_repo_idea_matrix_has_keep_adapt_ban_defer.py` | Bon pour plan scale; microservices lourds et execution rapide non adaptes maintenant. |
| Polymarket agents | Connectors, Pydantic models, RAG/evidence | DEFER/BAN | `docs/research`, futur `research` offline | `test_no_profit_promise_docs.py` | Garder modelisation/offline evidence. `trade.py`, keys, CLOB, signing BAN. |
| Lightweight Charts | Charts financiers canvas performants | KEEP | `src/hl_observer/ui/static`, `dashboard` | `test_no_fake_chart_or_fake_position_data.py` | Garder pour metagraphe fluide, mais uniquement avec donnees reelles de simulation. |

## Adaptation Hyperliquid obligatoire

Toute idee fusionnee doit passer par ces sources:

- REST `/info`: `allMids`, `l2Book`, `clearinghouseState`, `userFills`,
  `userFillsByTime`, `openOrders`, `frontendOpenOrders`, `candleSnapshot`.
- WS read-only: `allMids`, `trades`, `bbo`, `l2Book`, user streams uniquement
  sur shortlist bornee.
- SQLite local/runtime: snapshots, deltas, SignalCandidate, no_trade_decisions,
  paper_intents, paper_trades, source_health, feature rows.

## Regles de non-suppression

- Ne pas supprimer `hyper_smart_observer/dydx_v4/`; il reste legacy/mockable.
- Ne pas supprimer les documents d'idees externes; les enrichir et les relier a
  des modules/tests Hyperliquid.
- Ne pas fusionner du code externe brut; reprendre les concepts sous licence
  propre et implementations locales.
- Ne pas accepter une idee qui invente un PnL, lisse une perte, cache un refus
  ou pretend garantir un gain.

## Prochaine fusion prioritaire

1. Renforcer `market_signals` avec CVD, microprice, imbalance, volatility et
   source quality issus de `l2Book`, `trades`, `allMids`, `candleSnapshot`.
2. Brancher ces features dans `SignalCandidate` et `RiskEngine`.
3. Ajouter un journal decisionnel unique: evidence chain -> edge -> risk gates
   -> paper decision -> PnL realise/latent.
4. Garder le dashboard simulation comme lecture seule et afficher les raisons
   exactes des refus et pertes.

# HYPERSMART V12 — ÉTAT ACTUEL (snapshot 2026-06-21)

> Source de vérité : `docs/HYPERSMART_FUSION_ROADMAP_V12.md` + `AGENTS.md` (§6 capacités A–U).
> Ce document = photo factuelle de ce qui existe, vérifiée par scan de couverture des modules.

## Runtime réel

- **Runtime par défaut : Hyperliquid.** Le lanceur `LANCER_HYPERSMART.cmd` appelle
  `tools/start_hypersmart_simulation.ps1` → `python -m hl_observer ui` (port 8794) + un poller
  (`live-public-scan`, `live-user-fills-scan`, `copy-run`). dYdX (`hyper_smart_observer/dydx_v4/`)
  reste **dormant**, non monté dans l'UI, non importé par défaut.
- **Mode : simulation paper locale uniquement.** `HL_ENV=paper`, exécution mainnet/testnet = 0.
- **Données : réelles Hyperliquid** (`/info` REST 200 OK massif observé) ou état vide honnête.
- **Aucune donnée fabriquée active** : le générateur de prix démo (`dydx_v4/runtime_guards.neutral_demo_price`)
  a été neutralisé (renvoie le prix réel) ; `build_seed_shortlist()` renvoie `[]` ; aucun seed de
  wallet de test dans le code ; `demo_mode`/`allow_demo_fallback` = False par défaut.

## Deux packages

- `src/hl_observer/` — **runtime Hyperliquid principal** (UI, scan, scoring, edge, risk, paper, backtest).
- `hyper_smart_observer/` — base historique + dydx_v4 legacy (dormant) + quelques modules partagés
  (ledger/decision_ledger, paper_trading/exit_engine, backtesting/replay_engine, audit/safety_audit,
  pipeline/source_health).

## Couverture des capacités V12 (A–U) — scan de présence

| Cap | Capacité | Statut | Preuve (module clé) |
|---|---|---|---|
| A | Source Registry | **MANQUANT** (SourceHealth existe) | `hyper_smart_observer/pipeline/source_health.py` (santé OK ; registre formel absent) |
| B | Collection REST /info | PARTIAL | `src/hl_observer/hyperliquid/rest_info_client.py` |
| C | Scraping + proxy + cache | PARTIAL | `collection/proxy_pool.py`, `html_scraper.py`, `weight_budgeter.py` |
| D | WebSocket supervisor | PARTIAL | `realtime_monitor/ws_supervisor.py`, `wallets/public_trades_live.py` |
| E | RawStore + provenance | **MANQUANT** | (SQLite store existe, abstraction RawStore formelle absente) |
| F | Normalisation Pydantic | PARTIAL | `normalization/normalize.py` |
| G | Reconcile + dedupe | PARTIAL | `normalization/reconcile.py`, `signals/fill_admission.py` (dedupe) |
| H | Wallet discovery | PARTIAL | `wallets/discovery.py` |
| I | Wallet scoring | PARTIAL | `scoring/smart_money_filter.py`, `wallets/leaderboard_models.py` (priorité baleines) |
| J | Position lifecycle | PARTIAL | `signals/fill_admission.py`, `position_lifecycle/` |
| K | Market features | PARTIAL | `features/{microstructure,orderbook_imbalance,scan_features,volatility,direction}.py` |
| L | Edge / calibration | PARTIAL | `edge/{edge_calculator,fair_value,bias_model}.py`, `calibration/{brier,confidence_buckets}.py` |
| M | Strategy registry paper-only | **MANQUANT** | (stratégies dispersées ; pas de registre) |
| N | RiskEngine | PARTIAL | `risk/{risk_engine,exec_gates,circuit_breaker,loss_halts,var_cvar,trade_floor}.py` |
| O | DecisionLedger / Evidence | PARTIAL | `hyper_smart_observer/ledger/decision_ledger.py` |
| P | PaperEngine profond | PARTIAL | `paper_trading/exec_model.py`, `paper/paper_executor.py` |
| Q | ExitEngine | PARTIAL (SL/TP CÂBLÉ) | `paper_trading/sltp_runtime.py` (branché dans routes.py), `sl_tp.py` |
| R | Backtest / replay / WF | PARTIAL | `backtest/ledger_replay_v9.py`, `hyper_smart_observer/backtesting/replay_engine.py` |
| S | Dashboard / API / charts | PARTIAL | `ui/static/simulation_v2.html`, `ui/routes.py` |
| T | Agent tools / CLI | PARTIAL | `cli.py` (nombreuses commandes), `agent_tools/` |
| U | Safety audit / archive | PARTIAL | `audit/safety_audit.py`, `dashboard_truth/fake_data_detector.py` |

**Résumé : 18/21 DONE/PARTIAL, 3 MANQUANTS (A SourceRegistry, E RawStore, M StrategyRegistry).**

## Modules quant V9 récemment livrés (mappés sur V12)

- K/L : `features/{direction,bias_model}`, `edge/bias_model` câblé dans le scoreur live.
- N : `risk/circuit_breaker` (PnL-aware), `risk/entry_guard` (composition), `signals/opportunity_ranker` (score de puissance + diversification par coin).
- Q : `paper_trading/sl_tp` + `sltp_runtime` **câblé** (TP +0.30% / SL −0.40% / trailing au prix réel).
- I : `wallets/leaderboard_models.score_leaderboard_row` repondéré baleines (PnL/ROI/compte = 0.80).
- Freshness : `freshness/signal_decay` (courbe calibrée) câblée dans `realtime_magic_score`.

## Limites connues / pièges

- `hyper_smart_observer/dydx_v4/wallet_discovery.py` est CORROMPU (2409 octets null) — manipuler avec prudence.
- Sandbox d'analyse : divergence mount intermittente (bash lit des vues tronquées de gros fichiers `routes.py`/`.cmd`/HTML) → éditer via outil Edit (file-tools autoritatif), vérifier via Read file-tools, pas via bash.
- `cli.py` / `routes.py` (~3800 l.) : ne pas éditer en gros patch (risque troncature) — petits modules + insertions minimales validées AST.

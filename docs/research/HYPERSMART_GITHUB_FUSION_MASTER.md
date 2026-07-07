# HyperSmart GitHub Fusion Master

## Objectif

Construire HyperSmart comme smart-wallet observer et copy-wallet simulator
premium, Hyperliquid-first, read-only, simulation-only, paper/mock USDC. Les
depots GitHub externes sont des sources d'idees, pas des sources de code.

## Source GitHub inspiratrice

La matrice complete est dans
`docs/research/HYPERSMART_REPO_IDEA_MATRIX_FUSION.md`. Les sources principales
sont CloddsBot, Harrier toolkits, MrFadiAi Polymarket-bot,
polymarket_lp_tool, PolyWeather, Composio arbitrage bot, Awesome Prediction
Market Tools, PolyTerm, mlmodelpoly, polyrec, prediction-market-backtesting,
polybot, Polymarket agents et Lightweight Charts.

## Adaptation Hyperliquid

Le design fusionne les idees sous une doctrine unique:

```text
Hyperliquid-first
dYdX secondary/mockable
read-only collection
paper/mock USDC simulation
deny-by-default risk
no real execution
no fake dashboard data
```

Le pipeline canonique est:

```text
REST broad scan/backfill
-> WalletScoreV2 and shortlist
-> WS hot watch max 10 user-specific users
-> REST reconciliation
-> DeltaDetector
-> SignalCandidate only if evidence is strong
-> EdgeCalculator
-> RiskEngine deny-by-default
-> PaperEngine only
-> DecisionLedger and read-only dashboard
```

## Modules cibles

Architecture cible, avec equivalences locales pour eviter les doublons:

| Cible fusion | Equivalent local actuel | Statut |
| --- | --- | --- |
| `venues/base.py` | `src/hl_observer/data_sources/provider_registry.py`, `hyper_smart_observer/data_sources/provider_registry.py` | PARTIAL |
| `venues/hyperliquid_adapter.py` | `hyper_smart_observer/hyperliquid_client/info_client.py`, `src/hl_observer/hyperliquid/rest_info_client.py` | PARTIAL |
| `venues/dydx_adapter.py` | `hyper_smart_observer/dydx_v4/*` | PARTIAL |
| `pipeline/source_health.py` | `src/hl_observer/storage/repositories.py`, `SourceHealth` | PARTIAL |
| `pipeline/cursors.py` | `src/hl_observer/data_sources/historical_backfill_engine.py` | PARTIAL |
| `pipeline/fill_dedupe.py` | `hyper_smart_observer/copy_mode/snapshot_engine.py`, `src/hl_observer/storage/repositories.py` | PARTIAL |
| `models/common_data_model.py` | `hyper_smart_observer/models/common_data_model.py`, `hyper_smart_observer/hyperliquid_client/models.py`, `src/hl_observer/hyperliquid/schemas.py`, `src/hl_observer/storage/models.py` | DONE/PARTIAL |
| `market_signals/*` | `hyper_smart_observer/market_signals/*`, `src/hl_observer/edge/*`, `src/hl_observer/markets/*`, `src/hl_observer/copying/realtime_magic_score.py` | DONE/PARTIAL |
| `scoring/wallet_score_v2.py` | `hyper_smart_observer/scoring/*`, `src/hl_observer/wallets/scoring.py` | PARTIAL |
| `copy_mode/*` | `hyper_smart_observer/copy_mode/*` | DONE/PARTIAL |
| `risk_engine/*` | `hyper_smart_observer/risk_engine/*`, `src/hl_observer/risk/*` | PARTIAL |
| `paper/*` | `hyper_smart_observer/paper_trading/*`, `src/hl_observer/paper/*` | PARTIAL |
| `ledger/*` | `hyper_smart_observer/copy_mode/repository.py`, `storage` signal tables | PARTIAL |
| `dashboard/*` | `hyper_smart_observer/dashboard/*`, `src/hl_observer/ui/*` | PARTIAL |
| `agent_tools/*` | `hyper_smart_observer/agent_tools/*` | DONE |
| `backtesting/*` | `hyper_smart_observer/backtesting/*`, `src/hl_observer/backtest/*` | PARTIAL |

## Donnees Hyperliquid utilisees

- REST `/info`: `allMids`, `l2Book`, `clearinghouseState`, `userFills`,
  `userFillsByTime`, `openOrders`, `frontendOpenOrders`, `orderStatus`,
  `candleSnapshot`.
- WS read-only: `allMids`, `userFills`, `userEvents`, `openOrders`,
  `clearinghouseState`, `l2Book`, `trades`, `bbo`.
- Constraints: paginated time ranges, 20-level `l2Book`, snapshot then update
  semantics, rate-limit weights, and max 10 user-specific wallets for hot watch.

## Tests requis

- `test_start_script_preserves_6s_freshness_guard.py`
- `test_start_script_min_edge_bps_guard.py`
- `test_github_fusion_docs_exist.py`
- `test_repo_idea_matrix_has_keep_adapt_ban_defer.py`
- `test_no_external_code_copy_license_markers.py`
- `test_no_exchange_sdk_imports_or_actions.py`
- `test_no_private_key_signature_live_toggle.py`
- `test_no_polymarket_clob_or_private_key_imports.py`
- `test_no_fake_chart_or_fake_position_data.py`
- `test_no_profit_promise_docs.py`
- `test_hyperliquid_user_fills_by_time_aggregate_and_truncated_window.py`
- `test_hyperliquid_ws_subscription_ack_snapshot_dedupe.py`
- `test_market_mid_source_quality_fallback.py`
- `test_common_data_model_required_metadata.py`
- `test_scan_features_csv_json_export_per_run.py`
- `test_copy_run_network_read_collects_snapshots_deltas_signals_and_paper.py`
- `test_dashboard_reads_latest_scan_features_export.py`
- `test_agent_safe_manifest_readonly_only.py`
- `test_backtest_runtime_parity_same_models.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

- DONE: local-only scope, PS1 6000 ms freshness guard, 35 bps paper edge guard,
  bounded audit proof, openOrders-only no PaperIntent proof, reason alias.
- DONE in this pass: explicit Common Data Model metadata audit, pure CSV/JSON
  `scan_features` run export, and bounded `copy-run` scanner wiring that reads
  real `l2Book` data before persisting scan feature files. The static read-only
  dashboard now displays the latest real `scan_features` export or a clear
  empty-state.
- PARTIAL: broad scanner coverage, source health, dedupe, wallet intelligence,
  dashboard, backtest parity and market features already exist in several local
  modules but still need consolidation.
- TODO: extend `scan_features` into richer interactive chart views without
  introducing synthetic movement.
- DEFER: heavy microservices, ClickHouse/Redpanda/Grafana, RAG/evidence layer.
- BAN: any `/exchange` operational path, private key, signature, live toggle,
  executor-service, Polymarket CLOB, fake data, profit promise, LLM hot path.

# HyperSmart Hyperliquid Scan Strategy Fusion

## Objectif

Definir le scanner Hyperliquid-first qui decouvre, classe et suit les wallets
sans execution reelle.

## Source GitHub inspiratrice

Harrier toolkits pour adapter/risk layer, polymarket_lp_tool pour WS-first et
REST reconciliation, PolyWeather pour stale-state policy, Composio pour status
read-only, Awesome Prediction Market Tools pour leaderboards.

## Adaptation Hyperliquid

Scan obligatoire:

```text
manual seeds / watchlist / previous scans
-> REST broad scan/backfill with bounded cursors
-> WalletScoreV2 / copyability shortlist
-> WS hot watch max 10 user-specific users
-> REST reconciliation
-> append-only storage
```

Open orders are context only. Fills plus position delta are strong evidence.

## Modules cibles

- `hyper_smart_observer/hyperliquid_client/info_client.py`
- `src/hl_observer/hyperliquid/rest_info_client.py`
- `src/hl_observer/data_sources/historical_backfill_engine.py`
- `src/hl_observer/storage/repositories.py`
- `hyper_smart_observer/copy_mode/copy_loop.py`
- `hyper_smart_observer/realtime_monitor/*`

## Donnees Hyperliquid utilisees

`allMids`, `l2Book`, `clearinghouseState`, `userFills`,
`userFillsByTime`, `openOrders`, `frontendOpenOrders`, `candleSnapshot`, WS
`allMids`, `userFills`, `userEvents`, `openOrders`, `clearinghouseState`,
`l2Book`, `trades`, `bbo`.

## Tests requis

- `test_hyperliquid_user_fills_by_time_aggregate_and_truncated_window.py`
- `test_hyperliquid_rate_limit_weight_budget.py`
- `test_hyperliquid_ws_subscription_ack_snapshot_dedupe.py`
- `test_scanner_rest_broad_scan_to_shortlist.py`
- `test_scanner_ws_shortlist_max_10_users.py`
- `test_rest_reconciler_fills_missing_ws_event.py`
- `test_no_open_orders_only_paper_intent.py`
- `test_copy_run_network_read_collects_snapshots_deltas_signals_and_paper.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

PARTIAL. Existing code covers read-only `/info`, paginated fills with
aggregate/truncation/window metadata, source health, storage, market features,
WS snapshot dedupe, unique-user hot watch max 10, openOrders-only proof and
CSV/JSON `scan_features` run export from `run_copy_dry_run` after each bounded
network-read scan. TODO: broaden scanner coverage beyond the current shortlist
copy-run path without weakening rate-limit and no-fake-data guards.

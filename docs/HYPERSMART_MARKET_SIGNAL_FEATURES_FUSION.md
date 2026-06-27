# HyperSmart Market Signal Features Fusion

## Objectif

Produire des features marche explicables pour mesurer edge, degradation de
copie, liquidite et qualite des signaux avant toute simulation paper.

## Source GitHub inspiratrice

mlmodelpoly pour WS/OHLCV/CVD/VWAP/volatility/edge, polyrec pour CSV riche et
orderbook levels, polymarket_lp_tool pour mid stability and smoothing,
Lightweight Charts pour visualisation performante.

## Adaptation Hyperliquid

Features cibles:

```text
current_mid
bbo
spread_bps
microprice
depth_imbalance
depth_slope
volatility_context
mid_stability
liquidity_score
copy_degradation_bps
edge_remaining_bps
data_quality
source_health
scan_features CSV/JSON per run
```

No fake movement: every chart point must come from SQLite/runtime rows or an
empty state.

## Modules cibles

- `hyper_smart_observer/market_signals/*`
- `src/hl_observer/markets/*`
- `src/hl_observer/edge/*`
- `src/hl_observer/copying/realtime_magic_score.py`
- `hyper_smart_observer/copy_mode/edge.py`
- `hyper_smart_observer/dashboard/exporter.py`

## Donnees Hyperliquid utilisees

`allMids`, `l2Book` up to 20 levels, `trades`, `bbo`, `candleSnapshot`.

## Tests requis

- `test_market_signal_features_rich_export_schema.py`
- `test_scan_features_csv_json_export_per_run.py`
- `test_copy_run_network_read_collects_snapshots_deltas_signals_and_paper.py`
- `test_l2book_liquidity_score.py`
- `test_edge_remaining_uses_spread_fee_slippage_latency_copy_degradation.py`
- `test_no_fake_chart_or_fake_position_data.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

DONE/PARTIAL. Edge/degradation, MarketMid fallback, l2Book features, rich
export schema and deterministic `scan_features_<run>.csv/json` run export are
implemented in `hyper_smart_observer/market_signals`. `run_copy_dry_run` now
calls the pure exporter after a bounded network read and exposes row count plus
CSV/JSON paths in `CopyRunReport`. The read-only dashboard also displays the
latest real `scan_features` export with an explicit empty-state. Remaining
PARTIAL work is richer interactive chart consumption of those rows.

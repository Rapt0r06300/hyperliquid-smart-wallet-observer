# HyperSmart Dashboard Fusion

## Objectif

Afficher un dashboard premium read-only: scanner status, source health,
shortlist, deltas, no-trade reasons, signal candidates, edge, degradation,
paper/mock status, ledger and stale states.

## Source GitHub inspiratrice

CloddsBot pour WebChat/reports/artifacts, PolyWeather pour event-driven
dashboard and authoritative snapshots, Awesome Prediction Market Tools pour
wallet analytics benchmark, Lightweight Charts pour financial charts.

## Adaptation Hyperliquid

The dashboard is a read-only surface. It may show:

```text
scanner_running
source health
wallets scanned
shortlist
latest deltas
no-trade reasons
signal candidates
edge_remaining_bps
copy_degradation_bps
market_signal_features
latest scan_features export rows
liquidity/spread charts
paper/mock portfolio state
decision ledger
stale-state banners
empty states
```

It must not show fake positions, fake movement, wallet-connect, buy/sell,
execute, live toggle or profit promises.

## Modules cibles

- `hyper_smart_observer/dashboard/exporter.py`
- `src/hl_observer/ui/routes.py`
- `src/hl_observer/ui/static/simulation_v2.html`
- `src/hl_observer/ui/static/app.js`

## Donnees Hyperliquid utilisees

Local SQLite rows derived from read-only `allMids`, `l2Book`,
`userFillsByTime`, `clearinghouseState`, source health and DecisionLedger rows.

## Tests requis

- `test_hypersmart_dashboard_readonly.py`
- `test_dashboard_reads_latest_scan_features_export.py`
- `test_no_fake_chart_or_fake_position_data.py`
- `test_dashboard_stale_signal_not_paper_ready.py`
- `test_ui_no_dead_buttons.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

PARTIAL. Read-only dashboard tests exist, and the static dashboard now shows
the latest real `scan_features` export with an explicit empty-state when no
rows exist. Richer interactive chart and stale policy coverage remains TODO.

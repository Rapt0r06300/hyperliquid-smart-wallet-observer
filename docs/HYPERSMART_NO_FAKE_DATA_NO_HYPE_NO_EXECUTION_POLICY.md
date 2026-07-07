# HyperSmart No Fake Data No Hype No Execution Policy

## Objectif

Interdire les donnees inventees, les positions factices, les graphes fake, les
promesses de profit and all real execution paths.

## Source GitHub inspiratrice

PolyWeather for stale cached data blocking, Lightweight Charts for real chart
rendering only, Awesome Prediction Market Tools as product benchmark, CloddsBot
as a cautionary source where trading claims must be converted to diagnostics.

## Adaptation Hyperliquid

Dashboard and reports must show:

- real local rows from read-only collection;
- explicit empty states when data is missing;
- stale-state banners when freshness is degraded;
- no-trade reasons instead of synthetic "opportunities".

Forbidden language and features:

```text
profit guaranteed
guaranteed profit
risk-free profit
fake position
demo wallet as real
invented chart
mainnet execution
live trading
```

## Modules cibles

- `src/hl_observer/dashboard_truth/*`
- `src/hl_observer/ui/*`
- `hyper_smart_observer/dashboard/*`
- `docs/*`

## Donnees Hyperliquid utilisees

Only persisted read-only payloads from `/info`, WS snapshots/updates, source
health and ledger rows.

## Tests requis

- `test_no_fake_chart_or_fake_position_data.py`
- `test_no_profit_promise_docs.py`
- `test_hypersmart_dashboard_readonly.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

PARTIAL. Read-only UI tests exist. Broader docs wording and fake-data scanners
are added by the fusion tests.


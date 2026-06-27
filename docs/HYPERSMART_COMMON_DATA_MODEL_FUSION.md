# HyperSmart Common Data Model Fusion

## Objectif

Standardiser les objets transportes entre REST, WS, scoring, risk, paper,
ledger, dashboard et backtest.

## Source GitHub inspiratrice

prediction-market-backtesting pour runtime/backtest parity, PolyTerm pour JSON
schemas, Polymarket agents pour Pydantic-style research models, polyrec pour
feature rows riches.

## Adaptation Hyperliquid

Chaque objet doit porter: venue, source endpoint/channel, source timestamp,
local received timestamp, latency, raw hash/ref, data quality, stale flag,
schema version and adapter version.

Objects:

```text
NormalizedFill
NormalizedPosition
NormalizedOpenOrder
MarketMid
OrderBookSnapshot
MarketSignalFeatures
WalletSnapshot
CollectionRun
SourceHealth
LeaderDelta
SignalCandidate
RiskDecision
NoTradeDecision
PaperIntent
PaperTrade
DecisionLedgerEntry
DashboardEvent
```

## Modules cibles

- `hyper_smart_observer/hyperliquid_client/models.py`
- `hyper_smart_observer/models/common_data_model.py`
- `hyper_smart_observer/copy_mode/copy_models.py`
- `src/hl_observer/hyperliquid/schemas.py`
- `src/hl_observer/storage/models.py`

## Donnees Hyperliquid utilisees

All read-only REST and WS payloads listed in the scan strategy. `MarketMid`
must encode `MID_FROM_BOOK`, `MID_FROM_LAST_TRADE_FALLBACK`, or `MID_MISSING`.
Fill windows must encode `window_complete`, `truncated`,
`oldest_available_ts`, `stopped_reason`, and `aggregate_by_time_used`.

## Tests requis

- `test_common_data_model_required_metadata.py`
- `test_common_data_model_endpoint_channel_and_raw_aliases.py`
- `test_market_mid_source_quality_fallback.py`
- `test_hyperliquid_user_fills_by_time_aggregate_and_truncated_window.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

DONE/PARTIAL. Local dataclasses and Pydantic schemas exist,
`PaginationResult` records aggregate/truncation/window metadata, and
`hyper_smart_observer.models.common_data_model` now provides the single
consolidated metadata audit for every required CDM object. Remaining PARTIAL
work is field-by-field migration of all legacy dataclasses to carry the same
metadata natively.

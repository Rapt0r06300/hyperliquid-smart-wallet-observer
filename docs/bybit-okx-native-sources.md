# Bybit + OKX native market-data sources

Alina SmartFlow can now normalize public perpetual-market data from four venues into one fail-closed strategy-facing store:

- Hyperliquid — existing collector, normalized through `NativeVenueCoordinator.ingest_external_bbo`.
- Binance — existing collector, normalized through `NativeVenueCoordinator.ingest_external_bbo`.
- Bybit — native V5 public linear discovery + orderbook/ticker websocket adapter.
- OKX — native V5 public swap discovery + `books5`/ticker/funding/OI/mark-price websocket adapter.

## Safety model

The new sources are public/read-only only. They do not authenticate, sign requests, submit orders, or call trading endpoints. Every `NativeMarketSnapshot` carries `real_execution=False`.

Strategy-facing reads are deny-by-default: stale, crossed, invalid, desynchronized, or otherwise unmeasurable snapshots are excluded automatically.

## Core API

```python
from hl_observer.collection import NativeVenueCoordinator

coordinator = NativeVenueCoordinator(stale_after_ms=1_000)
registry = coordinator.discover()

# Existing Hyperliquid/Binance collectors can publish their public BBO here.
coordinator.ingest_external_bbo(
    venue="hyperliquid",
    coin="BTC",
    exchange_symbol="BTC",
    bid=100.0,
    ask=100.1,
    exchange_ts_ms=1_000,
    receive_ts_ms=1_010,
)

# Candidate assets require fresh coverage from at least two venues by default.
candidates = coordinator.candidate_coins(now_ms=1_100, min_venues=2)

# Cross-Venue receives executable bid/ask prices from every fresh venue.
rows = coordinator.cross_venue_rows("BTC", now_ms=1_100)

# Lead-Lag receives synchronized timestamped BBO/mid rows from the same store.
lead_lag = coordinator.lead_lag_rows("BTC", now_ms=1_100)
```

For four fresh venues, the store exposes all six venue pairs automatically: HL↔Binance, HL↔Bybit, HL↔OKX, Binance↔Bybit, Binance↔OKX, and Bybit↔OKX.

## Native collection

`await coordinator.run()` performs public Bybit + OKX discovery and starts both websocket collectors with bounded reconnect/backoff. The coordinator limits the number of subscribed symbols per venue (default 100) and prioritizes markets discovered on multiple venues.

## Tests

Focused coverage lives in:

- `tests/test_native_venue_market.py`
- `tests/test_bybit_market_data.py`
- `tests/test_okx_market_data.py`
- `tests/test_native_venue_coordinator.py`

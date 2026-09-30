# Bybit + OKX Native Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Bybit and OKX as native, public, read-only market-data sources and expose them with Hyperliquid/Binance to Cross-Venue and Lead-Lag.

**Architecture:** Each venue has a pure state/parser plus a small public REST/WS client. All venues normalize into `NativeMarketSnapshot` and a fail-closed `MultiVenueMarketStore`; `NativeVenueCoordinator` owns discovery/routing and strategy-facing views.

**Tech Stack:** Python 3.11+, httpx, websockets, pytest.

**Spec:** Conversation-approved native normalized multi-venue design.

## Global Constraints

- Read-only/public endpoints only; no API keys, signatures, orders, or exchange actions.
- Preserve `real_execution=False` in all normalized snapshots.
- Reject stale, desynchronized, crossed, or unmeasurable books from strategy-facing views.
- Reuse existing Hyperliquid/Binance collectors through normalized BBO ingestion.
- Bybit baseline: public V5 linear websocket orderbook + ticker.
- OKX baseline: public `books5` plus ticker/funding/open-interest/mark-price channels.

---

### Task 1: Canonical multi-venue store

**Files:**
- Create: `src/hl_observer/collection/native_venue_market.py`
- Test: `tests/test_native_venue_market.py`

**Interfaces:**
- Produces: `NativeMarketSnapshot`, `MultiVenueMarketStore`, `canonical_coin`.

- [x] Define failing tests for symbol normalization, freshness and four-venue strategy views.
- [x] Implement canonical snapshots, freshness gates, Cross-Source conversion and Lead-Lag rows.
- [x] Preserve deny-by-default quality states.

### Task 2: Bybit native adapter

**Files:**
- Create: `src/hl_observer/collection/bybit_market_data.py`
- Test: `tests/test_bybit_market_data.py`

**Interfaces:**
- Produces: `BybitMarketState`, `BybitPublicClient`, `parse_bybit_linear_instruments`.

- [x] Cover snapshot/delta order books, ticker metrics, discovery and fail-closed regressions.
- [x] Add public REST discovery and public websocket reconnect/backoff.

### Task 3: OKX native adapter

**Files:**
- Create: `src/hl_observer/collection/okx_market_data.py`
- Test: `tests/test_okx_market_data.py`

**Interfaces:**
- Produces: `OkxMarketState`, `OkxPublicClient`, `parse_okx_swap_instruments`.

- [x] Cover books5, ticker, funding, OI, mark price, discovery and sequence protection.
- [x] Add public REST discovery and public websocket reconnect/backoff.

### Task 4: Runtime coordinator and strategy wiring

**Files:**
- Create: `src/hl_observer/collection/native_venue_coordinator.py`
- Modify: `src/hl_observer/collection/__init__.py`
- Test: `tests/test_native_venue_coordinator.py`

**Interfaces:**
- Consumes: native Bybit/OKX adapters and existing Hyperliquid/Binance BBOs.
- Produces: `NativeVenueCoordinator.candidate_coins`, `.cross_venue_rows`, `.lead_lag_rows`.

- [x] Build a merged public instrument registry and feed `coin_universe`.
- [x] Route venue messages into the common store.
- [x] Add external BBO ingestion for existing Hyperliquid/Binance collectors.
- [x] Expose all six pair combinations when four venues are fresh.
- [x] Export the new public API from `hl_observer.collection`.

### Task 5: Verification and integration

**Files:**
- Test: `tests/test_native_venue_market.py`
- Test: `tests/test_bybit_market_data.py`
- Test: `tests/test_okx_market_data.py`
- Test: `tests/test_native_venue_coordinator.py`

- [ ] Run GitHub CI on the feature branch/PR.
- [ ] Fix every failure attributable to this branch.
- [ ] Review PR diff for accidental execution/auth code.
- [ ] Merge only after verification is green or explicitly document unrelated pre-existing CI failures.

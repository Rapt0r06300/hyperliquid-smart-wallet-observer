# dYdX Simulation Engine Handoff - 2026-06-14

## Scope

This handoff covers the dYdX v4 PAPER-ONLY simulation engine changes made in this run.
Update 2026-06-15: the simulation UI was then changed at the user's request to make
the metagraph react faster to paper mark-to-market changes. The change is visual/API
only and does not add execution capability.

Safety remains unchanged:

- READ-ONLY public data only.
- PAPER-ONLY simulation.
- No real order.
- No private key, seed, mnemonic, signature, deposit, withdrawal, or wallet connection.
- No private trading endpoint.

## Main Problems Observed

1. The engine used aggregate leader metrics too broadly.
   A wallet could look good globally while having no edge on the specific market being copied.

2. Funding was not subtracted early enough in the decision path.
   A signal could pass the edge gate and then carry adverse funding in the simulation.

3. Fresh consensus and stale consensus were not separated enough.
   Multi-wallet agreement is more useful when wallets converge within seconds, not minutes.

4. No-trade and paper decisions were not exported as a simple append-only diagnostic log.
   This made it hard to explain why the bot was losing or refusing.

5. Take-profit closed the whole paper position at TP.
   This could exit early instead of banking some profit and letting a runner continue.

## Implemented Changes

### 1. Market-Aware Leader Scoring

Files:

- `hyper_smart_observer/dydx_v4/leader_quality.py`
- `hyper_smart_observer/dydx_v4/wallet_discovery.py`
- `hyper_smart_observer/dydx_v4/live_observer.py`
- `tests/dydx_v4/test_leader_market_funding_consensus.py`

What changed:

- Added `LeaderMarketScore`.
- Added `score_trades_by_market(...)`.
- Added `get_wallet_market_metrics(...)`.
- Added `leader_recency_multiplier(...)`.
- `WalletScore` now stores:
  - `recent_score`
  - `market_stats`
- Indexer enrichment now computes per-market metrics from closed reconstructed trades.
- The live observer now prefers metrics for the actual `cluster.market_id`.
- If participating wallet metrics exist, they override aggregate wallet averages.

Expected effect:

- A strong BTC wallet no longer automatically boosts an ETH/SOL signal.
- The edge gate becomes more honest and more selective.

### 2. Consensus Freshness Bonus

Files:

- `hyper_smart_observer/dydx_v4/config.py`
- `hyper_smart_observer/dydx_v4/live_observer.py`
- `tests/dydx_v4/test_leader_market_funding_consensus.py`

What changed:

- Default `consensus_window_ms` moved from 10 minutes to 3 minutes.
- Added:
  - `consensus_recency_bonus_window_ms = 30000`
  - `consensus_recency_edge_multiplier = 1.06`
- The engine applies a small edge multiplier only if the first and last wallet in the consensus are close enough in time and the last action is still fresh.
- Accepted position reasons include `RECENT_CONSENSUS`.

Expected effect:

- Fresh clustered moves get slightly more weight.
- Old groups are less likely to look actionable.

### 3. Funding Cost in the Edge Gate

Files:

- `hyper_smart_observer/dydx_v4/config.py`
- `hyper_smart_observer/dydx_v4/live_observer.py`
- `tests/dydx_v4/test_leader_market_funding_consensus.py`

What changed:

- Added:
  - `funding_edge_enabled`
  - `funding_edge_horizon_hours`
- `_funding_penalty_bps(...)` estimates adverse funding from `nextFundingRate`.
- `calculate_edge(...)` now receives `funding_penalty_bps` before paper entry.

Expected effect:

- Positions with expensive adverse funding are refused earlier.
- The paper engine should stop accepting trades that only look profitable before carry costs.

### 4. Append-Only Decision Logs

Files:

- `hyper_smart_observer/dydx_v4/decision_log.py`
- `hyper_smart_observer/dydx_v4/config.py`
- `hyper_smart_observer/dydx_v4/live_observer.py`
- `hyper_smart_observer/dydx_v4/engine.py`
- `src/hl_observer/ui/dydx_routes.py`
- `tests/dydx_v4/test_dydx_refused_route.py`
- `tests/dydx_v4/test_leader_market_funding_consensus.py`

What changed:

- Added `DecisionLogger`.
- Default log path:
  - `logs/structured/decisions.jsonl`
- Config:
  - `DYDX_DECISION_LOG`
  - `DYDX_DECISION_LOG_PATH`
- Logged event types:
  - `NO_TRADE`
  - `PAPER_OPEN`
  - `PAPER_CLOSE`
  - `PAPER_PARTIAL_TP`
- Added engine accessors:
  - `get_recent_decisions(...)`
  - `get_refused_decisions(...)`
- Added read-only route:
  - `GET /api/dydx/refused`

Expected effect:

- The user can send `logs/structured/decisions.jsonl` to another agent.
- Refusals and accepted paper actions are explainable.
- Logs do not use SQLite and should not block archive hygiene.

### 5. ATR Partial Take-Profit

Files:

- `hyper_smart_observer/dydx_v4/config.py`
- `hyper_smart_observer/dydx_v4/live_observer.py`
- `tests/dydx_v4/test_leader_market_funding_consensus.py`

What changed:

- Added config:
  - `partial_tp_enabled`
  - `partial_tp_fraction`
  - `partial_tp2_multiplier`
- `PaperPositionState` now tracks:
  - `initial_size`
  - `partial_tp_taken`
  - `first_take_profit_price`
- On ATR-based positions only:
  - TP1 closes 50% by default.
  - Remaining size stays open.
  - Stop is moved to breakeven.
  - TP2 is moved farther using `partial_tp2_multiplier`.
  - A `PAPER_PARTIAL_TP` JSONL record is written.

Expected effect:

- The bot can bank partial profit without exiting the full simulated position too early.
- The runner can continue if the market keeps moving favorably.

## Tests Run

Targeted tests:

- `tests/dydx_v4/test_leader_market_funding_consensus.py`
- `tests/dydx_v4/test_dydx_refused_route.py`
- focused config tests

Full dYdX suite before the final report:

- `python -B -m pytest tests/dydx_v4/ -x -q -p no:cacheprovider ...`
- Result before final rerun: `256 passed, 1 warning`

Known warning:

- `hyper_smart_observer/dydx_v4/wallet_harvester.py:21`
- Python warns about an invalid escape sequence in ASCII art/doc text.
- This is not a trading or simulation failure.

## Security Scan Result

Command:

```powershell
rg -n "place_order|private_key|mnemonic|sign_transaction|broadcast" hyper_smart_observer
```

Findings are expected safety references only:

- safety scanners
- config fields that must remain false
- denied testnet Hyperliquid stub
- docs/logging text

No dYdX private execution path was added.

## Update 2026-06-15 - Realtime Simulation Tick

Files:

- `hyper_smart_observer/dydx_v4/engine.py`
- `src/hl_observer/ui/dydx_routes.py`
- `src/hl_observer/ui/static/simulation_v2.html`
- `tests/dydx_v4/test_engine_status_bridge.py`
- `tests/dydx_v4/test_dydx_refused_route.py`

What changed:

- Added `GET /api/dydx/realtime-tick`.
- The endpoint returns a lightweight paper-only snapshot:
  - equity
  - net, realized and unrealized PnL
  - open positions
  - current marks
  - scan/stream/market-flow summaries
- The endpoint sets no-cache headers and remains `GET` only.
- `DydxEngine.get_realtime_tick()` recalculates live observer status and can refresh
  public marks at most once per ~900 ms.
- `simulation_v2.html` now separates:
  - full refresh every 4 seconds for scan/wallet details
  - lightweight PnL tick every 750 ms
  - `requestAnimationFrame` rendering for smooth graph movement
- The graph keeps a live point updated every animation frame and stores one
  historical point per second.

Expected effect:

- The solde/PnL cards and metagraph should feel much closer to a trading screen.
- A paper position's unrealized PnL can move without waiting for the heavy scan refresh.
- The UI still reports only simulated paper mark-to-market, never real execution.

Verification:

- JavaScript parse check:
  - `node -e "... new Function(script) ..."`
  - Result: `simulation_v2.js syntax OK`
- Targeted pytest:
  - `29 passed, 18 warnings`
- Full dYdX pytest:
  - `262 passed, 18 warnings`

Browser note:

- The Codex browser check could not connect to `127.0.0.1:8794` during verification
  because the local server was not reachable from the test tab at that moment
  (`ERR_CONNECTION_REFUSED`). The code and tests are ready; reload the simulation page
  after restarting the launcher/server.

## Update 2026-06-15 - Async Discovery Proof

Files:

- `hyper_smart_observer/dydx_v4/wallet_discovery.py`
- `tests/dydx_v4/test_fast_scan_integration.py`

What changed:

- Added/verified `fast_discover_async(...)` using bounded concurrency.
- Added a deterministic test with 500 fake wallets, no network, concurrency 10.
- The test requires the async discovery path to shortlist 50 wallets in under 3 seconds.

Expected effect:

- The scanner has a tested fast path for larger candidate sets.
- This improves simulation responsiveness without bypassing API limits or adding unsafe scraping.

## Important Limits Still Remaining

1. Positive PnL is not guaranteed and must not be faked.
   The engine is more selective now, but real market outcomes remain uncertain.

2. Market-aware scoring depends on good reconstructed closed trades.
   If indexer enrichment has sparse data, the engine falls back conservatively.

3. Funding uses `nextFundingRate` as a short-horizon penalty.
   It is not a complete multi-hour funding model.

4. Partial TP is only enabled for ATR exits.
   Fixed-percent fallback exits still close the full position.

5. UI was not modified in this run by request.
   The route `/api/dydx/refused` is available for a future UI panel.

6. The engine still needs deeper backtest calibration on fresh sessions:
   - winrate by market
   - max drawdown
   - profit factor
   - edge buckets
   - latency buckets
   - flow vs REST source buckets

## Recommended Next Work

1. Run a 30-60 minute paper session and export `logs/structured/decisions.jsonl`.
2. Group results by `reason`, `market_id`, `side`, `event_type`, `edge_remaining_bps`, and `sizing_reason`.
3. Compare accepted trades vs refused trades to tune:
   - `DYDX_MIN_EDGE_BPS`
   - `DYDX_FLOW_MIN_TRADES`
   - `DYDX_MARKET_FLOW_MIN_IMBALANCE`
   - `DYDX_MAX_SPREAD_BPS`
   - `DYDX_PARTIAL_TP_FRACTION`
4. Add a dashboard panel that reads `/api/dydx/refused`.
5. Add serious backtest reporting from JSONL plus closed trades.
6. Add a calibration report that recommends settings only; never auto-applies them.

## Handoff Summary

The simulation engine is now more conservative, more market-aware, more funding-aware, and much more diagnosable. It should not be presented as a guaranteed-profit bot. The next agent should use the new decision logs to tune the strategy empirically instead of forcing fake positive PnL.

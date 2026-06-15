# dYdX / HyperSmart Simulation Log Audit - 2026-06-15

## Scope

Source analyzed:

- `C:\Users\flo\Desktop\Projet invest\logs.zip`
- Main structured source inside the archive: `logs/structured/decisions.jsonl`
- UI export source inside the archive: `logs/logs à envoyer/*`

Mode:

- Paper simulation only.
- Read-only market data only.
- No real order.
- No private key.
- No signature.
- No mainnet executor or testnet executor.

## Key Finding

The simulation engine did produce decisions, but the legacy UI/export path was often looking at the wrong or empty files.

Observed mismatch:

- `logs/structured/decisions.jsonl` contained real paper decisions.
- `logs/logs à envoyer/simulation_decisions_latest.jsonl` was empty or unavailable in the archive path encoding.
- `simulation_snapshot_latest.json` showed `follow_decisions=0`, `fresh_opportunities_accepted=0`, `decision_log_pnl.events=0`.

Result: the dashboard could say "nothing is happening" while the paper engine had actually opened, closed, refused, and partially closed simulated positions.

## Structured Log Metrics

From `logs/structured/decisions.jsonl`:

- Total decisions: 124.
- `NO_TRADE`: 108.
- `PAPER_OPEN`: 8.
- `PAPER_CLOSE`: 7.
- `PAPER_PARTIAL_TP`: 1.
- Accepted paper actions: 16.
- Refused signals: 108.
- Event-level paper PnL: `+1.134160 USDC`.
- Last cumulative paper PnL in engine log: `+1.134252 USDC`.
- Last simulated equity in engine log: `1001.134252 USDC`.
- Event-level fees detected: `0.584340 USDC`.

The event-level PnL is now computed correctly:

- `PAPER_OPEN` = entry fee cost, usually negative.
- `PAPER_CLOSE` = realized trade net PnL.
- `PAPER_PARTIAL_TP` = realized partial TP net PnL.
- `NO_TRADE` = zero PnL impact.

Previous bug risk:

- `net_pnl_usdc` in dYdX structured rows is cumulative session PnL.
- Summing cumulative `net_pnl_usdc` across every row is mathematically wrong.
- The analyzer now uses per-event PnL fields and ignores cumulative PnL on `NO_TRADE`.

## Main Refusal Reasons

Top refusal reasons in the structured log:

1. `STALE_SIGNAL`: 45.
2. `MAX_OPEN_REACHED`: 32.
3. `ALREADY_IN_POSITION`: 14.
4. `SPREAD_TOO_WIDE`: 6.
5. `TREND_OPPOSITION`: 5.
6. `REOPEN_COOLDOWN`: 3.
7. `CORRELATED_EXPOSURE`: 2.
8. `EDGE_INSUFFICIENT`: 1.

Signal age diagnostics:

- `NO_TRADE` stale age min: `20247 ms`.
- `NO_TRADE` stale age median: `36305 ms`.
- `NO_TRADE` stale age p95: `59005 ms`.
- Accepted open last-age median: `5806 ms`.
- Worst accepted open last-age: `23177 ms`.

Interpretation:

- The biggest quality problem is freshness, not just wallet count.
- If the engine receives the signal after 20-60 seconds, copy edge is likely degraded.
- The UI must surface this clearly instead of just showing "red" or "0".

## Decision Quality Findings

Low-edge accepted entry found:

- `DOGE-USD LONG`, edge `5.9576 bps`, 3 wallets.

Single-wallet accepted entries found:

- `SOL-USD LONG`, edge `28.9877 bps`, wallet_count `1`.
- `SOL-USD LONG`, edge `42.8444 bps`, wallet_count `1`.
- `SOL-USD LONG`, edge `23.1383 bps`, wallet_count `1`.

Important nuance:

- Some single-wallet or flow entries can still be profitable.
- But they should be clearly labeled as market-flow/solo signals, not wallet-consensus signals.
- The next phase should split "multi-wallet consensus" and "market-flow momentum" on the dashboard and in risk logs.

## Fixes Implemented

### 1. Legacy log analyzer now reads dYdX structured decisions

Files changed:

- `src/hl_observer/simulation/decision_replay_analyzer.py`
- `src/hl_observer/simulation/log_metrics.py`

Behavior:

- Prefers small/fresh files first:
  - `simulation_decisions_latest.jsonl`
  - `logs/structured/decisions.jsonl`
  - `cli_simulation_decisions_latest.jsonl`
  - `simulation_decisions_append_only.jsonl`
- Avoids loading huge multi-GB append-only logs first.
- Bridges the dYdX structured paper engine into legacy UI/CLI diagnostics.

### 2. dYdX event-level PnL normalization

Implemented mapping:

- `NO_TRADE` -> no PnL effect.
- `PAPER_OPEN` -> `-fee_paid`.
- `PAPER_CLOSE` -> `net_pnl`.
- `PAPER_PARTIAL_TP` -> `net_pnl`.

Why:

- dYdX rows can include `net_pnl_usdc` as cumulative session PnL.
- Cumulative values must not be summed row by row.

### 3. Streaming log analyzer now avoids double-counting

File changed:

- `src/hl_observer/simulation/log_metrics.py`

Behavior:

- Uses one active source in priority order.
- Prevents double-counting `latest`, `cli`, `append_only`, and `structured` logs.
- Avoids accidental UI stalls on very large append-only logs.

### 4. Decision logger now records session state on every decision

File changed:

- `hyper_smart_observer/dydx_v4/live_observer.py`

Each future decision row includes:

- `session_id`
- `net_pnl_usdc`
- `equity_usdc`
- `paper_only=true`
- `read_only=true`

Why:

- Future logs sent to ChatGPT/Claude can be analyzed without guessing which session or wallet balance they belong to.
- Every refusal and every paper action is tied to the exact simulated portfolio state.

## Tests Added Or Updated

Files changed:

- `tests/test_realtime_replay_and_latency.py`
- `tests/test_logs_analyzer_streaming.py`
- `tests/dydx_v4/test_leader_market_funding_consensus.py`

New coverage:

- Empty latest export + active `logs/structured/decisions.jsonl`.
- Correct dYdX event-level PnL calculation.
- Correct dYdX fee calculation.
- Streaming analyzer uses `decisions.jsonl` and does not double count.
- `NO_TRADE` rows do not pollute PnL with cumulative session values.
- Future decision rows include `session_id`, `net_pnl_usdc`, `equity_usdc`, `paper_only`, and `read_only`.

## Tests Run

Because Windows temporary folder `C:\Users\flo\AppData\Local\Temp\pytest-of-flo` was locked, tests were run with:

- `TMP=C:\Users\flo\Documents\Codex\pytest-tmp`
- `TEMP=C:\Users\flo\Documents\Codex\pytest-tmp`
- `--basetemp=C:\Users\flo\Documents\Codex\pytest-*`
- `-p no:cacheprovider`

Results:

- `tests/test_realtime_replay_and_latency.py tests/test_logs_analyzer_streaming.py`: `12 passed`.
- `tests/dydx_v4/test_leader_market_funding_consensus.py tests/dydx_v4/test_engine_status_bridge.py tests/dydx_v4/test_dydx_refused_route.py`: `10 passed, 18 warnings`.
- Prior targeted dYdX suite in this workstream: `29 passed, 18 warnings`.
- Prior full dYdX suite in this workstream: `262 passed, 18 warnings`.

## Local CLI Verification After Fix

Command:

```powershell
python -m hl_observer logs-analyze --from-logs "logs\logs à envoyer"
```

Result after the fix:

- `source_files=decisions.jsonl`
- `total_decisions=194`
- `accepted=53`
- `refused=141`
- `gross_pnl_usdc=3.350700`
- `net_pnl_usdc=1.754608`
- `fees_usdc=1.596092`
- `profit_factor_net=2.432108`
- `top_refusal_reasons` now excludes normal close reasons such as `STOP_LOSS`, `TAKE_PROFIT`, and `TAKE_PROFIT_PARTIAL`.

Important interpretation:

- The currently available local structured log is net-positive in paper simulation.
- Fees are high relative to gross PnL (`fee_drag_ratio=0.476346`), so the next optimization should reduce weak entries and churn.
- Positive current logs do not guarantee future profit.

## Remaining Engineering Problems

### 1. Freshness is still the main bottleneck

Problem:

- `STALE_SIGNAL` dominates.
- Stale no-trades are 20-60 seconds old.
- Copy logic should not chase old opens.

Recommended next fix:

- Separate signal age gates:
  - hard entry gate for new opens;
  - looser exit monitoring gate;
  - dashboard freshness panel showing p50/p95 latency.
- Prefer WebSocket / streaming fills for fresh signals.
- Keep REST as fallback, not primary hot-path.

### 2. `ALREADY_IN_POSITION` should become position management

Problem:

- Repeated same-side signals are currently counted mostly as no-trades.
- But they can be useful confirmations for trailing stop, confidence, and TP management.

Recommended next fix:

- Add `POSITION_CONFIRMATION` event type.
- Do not open a duplicate paper position by default.
- Use confirmations to:
  - tighten trailing stop if PnL positive;
  - increase confidence;
  - record multi-wallet support;
  - optionally allow one controlled add only under strong edge.

### 3. `MAX_OPEN_REACHED` blocks opportunities without ranking replacements

Problem:

- When max positions are reached, the engine refuses new signals even if they are much stronger.

Recommended next fix:

- Add a paper-only capital allocator:
  - rank open positions by edge, freshness, unrealized PnL, correlation, and signal support;
  - if a new signal is materially better, close or reduce the weakest paper position locally;
  - log `POSITION_REBALANCE_PAPER_ONLY`.

### 4. Solo flow signals need clearer treatment

Problem:

- Some entries have `wallet_count=1`.
- The user expects multi-wallet consensus.
- Market-flow signals are not the same as wallet consensus.

Recommended next fix:

- Dashboard and logs must label:
  - `MULTI_WALLET_CONSENSUS`;
  - `MARKET_FLOW_MOMENTUM`;
  - `SOLO_WALLET_OBSERVATION`.
- Apply stricter edge/freshness to solo or flow signals.

### 5. UI must read the same state as the engine

Problem:

- UI/export and engine logs can diverge.

Recommended next fix:

- Make `logs/structured/decisions.jsonl` the canonical decision source for dYdX simulation.
- Generate `logs/logs à envoyer/*` from structured state, not a separate empty event list.
- Show source filename and last decision timestamp in the UI.

## Safety Confirmation

This audit and the implemented fixes preserve:

- No real order.
- No private key.
- No signature.
- No exchange/execution endpoint.
- Paper simulation only.
- Read-only data path.
- No fake positive PnL.
- No guarantee of profit.
- Score is not a signal.
- Paper trade is not an order.

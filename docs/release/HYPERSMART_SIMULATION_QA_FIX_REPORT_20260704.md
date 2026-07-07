# HyperSmart Simulation QA Fix Report - 2026-07-04

## Scope

Local Hyperliquid paper simulation only. No real order, no private key, no signature, no wallet connect, no external execution.

## Problems Confirmed

1. The running UI server had a crash path in `status_routes.py`:
   `KeyError: 'ext_rezzecup_whale_mirror_primary|BNB|SHORT'`.
   Cause: a quality-exit close path could delete a paper position that had already been removed.

2. The launcher/poller sometimes failed to write:
   `runtime/data/hypersmart_engine_status.json`.
   Cause: Windows file locking during concurrent read/write, producing stale/offline UI status.

3. The UI could render invalid legacy positions as `?`.
   Cause: older paper position rows sometimes only had the market encoded in `position_id`.

4. Current logs show negative paper PnL is not a graph fabrication.
   The ledger/dashboard reconciliation reports OK, but the strategy is being hurt by fee drag, weak single-wallet edge, micro-notional sizing and low net profit factor.

## Fixes Applied

1. `src/hl_observer/ui/status_routes.py`
   - Added defensive checks before quality-exit close ledger writes.
   - Replaced fragile direct deletes with safe `pop`.
   - Added skip reporting for already-removed positions.
   - Added robust coin inference from legacy `position_id`.
   - Filtered unrecoverable invalid positions instead of rendering `?`.

2. `src/hl_observer/ui/static/simulation_v2.html`
   - Keeps the simulation page on the last valid position set.
   - Filters invalid position rows before rendering.
   - Avoids turning a slow heavy overview call into a false offline state.
   - Keeps the metagraph tied to the fast status endpoint and valid mark-to-market values.

3. `tools/hypersmart_simulation_poll_loop.ps1`
   - Replaced direct `Set-Content` writes of engine status with retrying atomic JSON writes.

4. `tools/start_hypersmart_simulation.ps1`
   - Same atomic JSON write protection for launcher status.

5. `src/hl_observer/runtime/fusion_heartbeat_input.py`
   - Added atomic JSON write with short Windows retry loop.

6. `tests/test_ui_simulation_status_fast.py`
   - Added coverage for legacy coin inference and unrecoverable invalid-position filtering.

## Live Runtime Observation

The currently running server on port `8794` was still using the old in-memory code when inspected. It answered `/api/simulation/status` successfully, but its stderr still contained the old `del positions[position_key]` crash trace. Restart `LANCER_HYPERSMART.cmd` to load the fixed files.

## Current PnL Diagnosis From Fresh Logs

`profitability-diagnostics`:

- Gross PnL: `-0.015988 USDC`
- Net PnL: `-0.094008 USDC`
- Fees: `0.352243 USDC`
- Fee drag ratio: `22.031711`
- Net winrate: `0.500000`
- Net profit factor: `0.652077`

`pnl-audit`:

- Effective paper PnL: `-0.482980 USDC`
- Session equity: `999.517020 USDT`
- PnL reliability: `OK`
- Paper ledger reconciliation: OK
- Worst wallet source: `ext_rezzecup_whale_mirror_primary`
- Main loss causes: fee drag, weak single-wallet edge, micro-trades, low net profit factor.

## Replay / Optimization Result

Commands run:

- `strategy-tournament`
- `optimize-profit-config`
- `walk-forward-profit-validation`
- `out-of-sample-report`
- `anti-overfit-audit`
- `best-config-report`

Result: no candidate strategy improved robust net profit factor on current logs. Best robust config is `no_trade_baseline`. Therefore no new aggressive flag was activated automatically.

## Tests And Audits

- `python -m pytest -q tests/test_ui_simulation_status_fast.py tests/test_simulation_v2_normal_pnl_ledger_ui.py`
  - `36 passed`
- targeted simulation/persistence/audit tests
  - `60 passed`
- `python -m pytest -q tests/test_hypersmart_*.py`
  - `297 passed`
- `python -m pytest -q`
  - `2248 passed`
- `python -m hyper_smart_observer.app.main --safety-check`
  - OK
- `python -m hyper_smart_observer.app.main --audit-safety`
  - OK
- `python -m hyper_smart_observer.app.main --runtime-check`
  - archive ready, legacy DB in logs detected and excluded
- `python -m hyper_smart_observer.app.main --runtime-clean-report`
  - no deletion, clean archive policy confirmed
- `python -m hl_observer.cli archive-audit`
  - OK

## Next Exact Priority

1. Restart `LANCER_HYPERSMART.cmd` so the live server uses the fixed code.
2. Let it run long enough to produce fresh post-fix logs.
3. Re-run `pnl-audit` and `profitability-diagnostics`.
4. Do not activate new flags unless replay/walk-forward improves net profit factor after fees.
5. Focus next on reducing fee drag: minimum notional, stronger multi-wallet consensus, stricter single-wallet rejection, and coin/wallet quarantine after loss streaks.

## Safety Confirmation

- No real order.
- No private key.
- No signature.
- No wallet connect.
- No `/exchange` operational path.
- Hyperliquid read-only + local paper simulation.
- PnL remains truthful: no fake gain, no fake chart.

# HyperSmart V7 - Execution Status

Date: 2026-06-19

## Read

- `docs/CODEX_HYPERSMART_MASTER_PLAN_V7_ACTION_BOUNDARY.md`
- `AGENTS.md`
- Hyperliquid official docs:
  - Info endpoint
  - WebSocket subscriptions
  - Rate limits and user limits
  - Exchange endpoint, only to confirm it remains outside runtime

## Modified

- `src/hl_observer/ui/status_routes.py`
- `src/hl_observer/ui/app.py`
- `src/hl_observer/ui/routes.py`
- `src/hl_observer/ui/static/simulation_v2.html`
- `tools/hypersmart_simulation_poll_loop.ps1`
- `tests/test_ui_simulation_status_fast.py`

## DONE

- Kept the existing official simulation UI: `src/hl_observer/ui/static/simulation_v2.html`.
- Did not create a second simulation, demo simulation, fake PnL source, fake position source, or fake chart source.
- Added a lightweight engine heartbeat at `runtime/data/hypersmart_engine_status.json`.
- The heartbeat is status-only: it reports phase, poll index, scan metrics, read-only flag, simulation-only flag, and `external_action=false`.
- `/api/simulation/status` now exposes:
  - paper equity from the existing `UiState`;
  - paper PnL from the existing `UiState`;
  - existing paper positions;
  - `server_running`;
  - `engine_running`;
  - `engine_status`;
  - scanner counters parsed from the heartbeat.
- `/api/simulation/status` now mark-to-markets existing open paper positions against local Hyperliquid `market_snapshots`.
- The fast status endpoint enriches open positions with `entry_price`, `mark_price`, `market_mark_available`, `mark_source`, `notional_usdt`, and `unrealized_pnl_usdc`, which is the shape already expected by `simulation_v2.html`.
- If no Hyperliquid mark is available for an open position, the endpoint reports `MARK_MISSING_NO_FAST_MTM` and does not fabricate price movement.
- If there is no paper position, the endpoint returns an honest empty state and proves `no_fallback_position_created=true`.
- Fast mark-to-market points are appended to the existing `UiState.simulation_equity_history` and persisted through the existing state file; no new portfolio, no new page, and no parallel fake graph were added.
- The single launcher now performs explicit post-start checks:
  - warns if `/api/simulation/overview` does not answer after startup;
  - warns if the UI process exits immediately;
  - warns if the simulation poller exits immediately.
- The launcher and poller now use the same canonical `logs à envoyer` path construction, avoiding old mojibake/duplicate folder drift.
- The simulation page no longer lets the secondary fast-status poll overwrite `Hyperliquid · moteur actif` or `Serveur OK · moteur a relancer` with a generic read-only badge.
- The dashboard tick can now show whether the engine is actually alive instead of staying on a stale "starting" state.
- Fixed the UI route/event-loop safety issue by keeping blocking SQLite-style status routes synchronous, so FastAPI can run them outside the event loop.
- Confirmed V7 vertical slice tests still pass for:
  - position lifecycle open/add/reduce/close;
  - ambiguous flip => no-trade path;
  - leader reduce/close -> local paper exit engine;
  - no matching paper position -> no-trade;
  - PaperEngine realized/unrealized PnL/equity/drawdown;
  - decision ledger/evidence chain;
  - runtime/backtest parity fixtures.

## PARTIAL

- The simulation UI now sees the engine heartbeat quickly, but a full 10-minute QA observation against the live launcher was not completed in this slice.
- The heartbeat reports the poller state and metrics, but deeper per-decision evidence remains in the existing logs/DB rather than in the heartbeat payload.
- Official docs were rechecked for endpoint boundaries; no new external action path was added.
- The fast endpoint uses local snapshots already stored in SQLite. It does not itself open a network stream, so real-time smoothness still depends on the launcher/poller continuing to collect fresh Hyperliquid marks.
- If the user closes the visible launcher with `Q`, the local server and poller stop by design. A browser tab left open after that will show a disconnected state until `LANCER_HYPERSMART.cmd` is relaunched.

## BLOCKED

- None for this slice.

## DEFER

- Long-running QA with the real launcher open for 10 minutes.
- More granular dashboard display of each scan phase's last duration and last error.
- Reconcile heartbeat metrics with detailed `logs/logs a envoyer` decision JSONL.
- Compare runtime paper vs replay paper in the dashboard.

## Tests Run

```powershell
python -m pytest -q tests/test_ui_simulation_status_fast.py tests/test_hypersmart_single_launcher.py tests/dydx_v4/test_real_simulation_no_demo.py tests/test_launcher_guards_match_runtime.py
```

Result: `19 passed`.

```powershell
python -m pytest -q tests/test_position_lifecycle_open_add_reduce_close.py tests/test_position_lifecycle_flip_unknown_no_trade.py tests/test_exit_engine_follow_reduce_close.py tests/test_exit_engine_no_matching_paper_position.py tests/test_paper_engine_realized_unrealized_pnl_equity.py tests/test_decision_ledger_evidence_chain.py tests/test_evidence_chain_reconstructs_decision.py tests/test_backtest_runtime_parity_market_features_reason_codes.py
```

Result: `18 passed`.

```powershell
python -m pytest -q tests/test_ui_simulation_status_fast.py tests/test_hypersmart_single_launcher.py
```

Result: `11 passed`.

```powershell
python -m pytest -q tests/test_ui_simulation_status_fast.py tests/test_hypersmart_single_launcher.py tests/test_no_fake_chart_or_fake_position_data.py
```

Result: `15 passed`, then `16 passed` after launcher/status-badge hardening.

```powershell
$null = [scriptblock]::Create((Get-Content -Raw tools/start_hypersmart_simulation.ps1))
$null = [scriptblock]::Create((Get-Content -Raw tools/hypersmart_simulation_poll_loop.ps1))
```

Result: both PowerShell scripts parse successfully.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\flo\Desktop\Projet invest\tools\hypersmart_simulation_poll_loop.ps1" -Root "C:\Users\flo\Desktop\Projet invest" -MaxRuns 0
```

Result: passed. It wrote `runtime/data/hypersmart_engine_status.json` and did not perform a network scan.

## Next Exact Action

Run the real launcher, observe `/api/simulation/status` and `/api/simulation/overview` for 10 minutes, then reconcile:

1. whether `engine_running` stays true while the launcher is open;
2. whether `leaders_selected`, `fresh_entry_deltas`, and `virtual_refusals_logged` move every poll;
3. whether no-trade reasons match the decision logs;
4. whether accepted paper entries come only from real Hyperliquid-derived events;
5. whether paper equity/PnL remains sourced from `UiState` plus local Hyperliquid market marks, not from synthetic chart movement;
6. whether the poller is collecting `allMids` / `publicTradesWS` often enough for the existing paper positions to mark-to-market every visible tick.

## Guardrail Confirmation

- Runtime default remains Hyperliquid.
- Simulation remains local/paper only.
- Existing PaperEngine is preserved.
- The existing simulation page is preserved.
- No `/exchange` runtime path was added.
- No real order path was added.
- No private key path was added.
- No signature path was added.
- No wallet connect path was added.
- No fake PnL or fake chart source was added.
- No fallback paper position was added when no signal exists.

## 2026-06-19 Market Mark Refresh Slice

### Modified

- `src/hl_observer/markets/scanner.py`
- `tools/hypersmart_simulation_poll_loop.ps1`
- `tests/test_market_universe.py`
- `tests/test_hypersmart_single_launcher.py`

### Done

- `discover-markets --store` now stores `MarketSnapshot(source="allMids")`, not only raw `allMids` events and market-universe rows.
- The simulation poll loop now refreshes Hyperliquid `allMids` market marks on every bounded poll before wallet scans and `copy-run`.
- This gives `/api/simulation/status` fresher local Hyperliquid marks for existing paper positions, without creating fake chart movement or fake paper positions.
- The launcher remains the single official entrypoint and the existing simulation remains the only simulation UI.

### Still True

- Accepted entries still depend on real leader/fill/delta signals and risk gates.
- No paper position is invented to force movement.
- No `/exchange`, real order, private key, signature, or wallet connect path was added.

### Tests Added

```powershell
python -m pytest -q tests/test_market_universe.py tests/test_hypersmart_single_launcher.py tests/test_ui_simulation_status_fast.py tests/test_no_fake_chart_or_fake_position_data.py
```

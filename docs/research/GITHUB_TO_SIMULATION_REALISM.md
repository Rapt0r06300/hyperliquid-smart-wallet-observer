# GitHub To Simulation Realism

## Purpose
External GitHub ideas are valuable only if they make paper PnL more realistic and auditable.

## Realism rules added in Phase 0
- Every simulated action can become a `PaperEvent`.
- Fees are explicit.
- Funding cash impact is explicit.
- Open positions have mark-to-market unrealized PnL.
- Closed positions update realized PnL.
- Equity and drawdown are computed from ledger state.
- Reconciliation checks whether PnL equations drift.
- Orderbook execution can return partial or missed fills.

## Next wiring targets
1. Existing `PaperEngine.apply_delta` should emit `PaperLedger` events.
2. UI `simulation_v2.html` should read the ledger snapshot via status payloads.
3. Audit reports should reconcile dashboard PnL against ledger PnL.
4. Backtests should replay the same event model.

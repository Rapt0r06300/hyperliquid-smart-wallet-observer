# H—T-42 — Cross‑Venue runtime/test mapping

Exact audit baseline: `a7d323ccd273cc9b6ddd3cef59b6efe9dd3d6f4c`.

Scope: Cross‑Venue technical completion only. Paper/read-only remains mandatory; this document does not certify profitability and does not revive the historical taker‑taker hypothesis.

## Evidence map

| Requirement | Runtime / test evidence | Classification |
|---|---|---|
| Paper-only execution | `src/hl_observer/paper_trading/cross_venue_execution.py` exposes `paper_only=True`, `real_execution=False`; canonical execution has no signer/order client | ALREADY_IMPLEMENTED |
| Two-leg non-atomic state machine | `CrossVenueExecutionState`, `execute_non_atomic_cross_venue`, distinct LEG1/LEG2 snapshots and causal unwind | ALREADY_IMPLEMENTED |
| Partial/missed second leg | `tests/test_cross_venue_non_atomic_execution_v2.py` verifies partial LEG2, failed LEG2, causal unwind and final flat ledger | ALREADY_IMPLEMENTED |
| Measured latency / skew discipline | `MeasuredLatencyDistribution` requires measured samples; scenario validator rejects latency below measured percentile and reused/predating snapshots | ALREADY_IMPLEMENTED |
| Executable bid/ask + depth/VWAP | Cross‑Venue legs route through canonical `execute_paper_intent`, which consumes `ExecutionTruth` and the strict book execution model instead of a mid-price fill | ALREADY_IMPLEMENTED |
| Instrument mapping | `src/hl_observer/config/cross_venue_instruments.py` maps HL coins to explicit Binance perpetual symbols and rejects unsupported/mismatched symbols | ALREADY_IMPLEMENTED |
| Multipliers / quote / settlement currency | `mapping_record` exposes `contract_multiplier`, `quote_currency`, `settlement_currency`, `unit_equivalent`; multiplier-1000 contracts are not marked exact | ALREADY_IMPLEMENTED / FAIL_CLOSED |
| Mapping tests | `tests/test_cross_venue_instruments_mapping.py` covers BTC exact mapping, unsupported HYPE, wrong symbol and 1000× PEPE non-equivalence | ALREADY_IMPLEMENTED |
| Snapshot freshness | Cross‑Venue passes `max_book_age_ms` into canonical execution; strict execution truth rejects observations outside the age budget | ALREADY_IMPLEMENTED, targeted Cross‑Venue characterization still desirable |
| Full-cost accounting | Canonical execution exposes fees/slippage/latency cost fields; Cross‑Venue residual unwind PnL is reconciled in the paper ledger | ALREADY_IMPLEMENTED, exact four-fill round-trip certification still OPEN |
| Four-fill accounting when applicable | Entry legs are modeled; residual unwind is modeled. A complete matched position round-trip needs explicit exit-leg evidence before technical Done | OPEN |
| Historical taker-taker KILL | No claim in this mapping re-labels the killed micro-edge as executable alpha | HISTORICAL/KILLED preserved |

## Remaining Done-contract gaps

1. Add/identify an exact Cross‑Venue test proving stale delayed books are rejected fail-closed at the lane boundary.
2. Prove complete matched-position exit accounting with four executable fills when a round trip is evaluated, including fees/slippage/depth and final flat state.
3. Run targeted Cross‑Venue tests and relevant regression at the exact delivery SHA; only then check the corresponding AgiFlow acceptance criteria.

No criterion should be closed from this document alone when runtime/test evidence is still marked OPEN.

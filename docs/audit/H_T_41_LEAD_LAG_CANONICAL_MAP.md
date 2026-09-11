# H—T-41 — Lead-Lag canonical implementation map

Status: **IN PROGRESS**  
Scope: roadmap V5 §11 + validated 776+ Lead-Lag additions  
Contract: technical completion only; no +4 USD / positive-PnL requirement.

## Invariants

- PAPER / READ-ONLY only; no real execution.
- TRAIN selection must remain causally separated from held-out / freeze evidence.
- Observable clocks and source provenance are mandatory and fail closed.
- Multiple-testing family size is predeclared before replay; no outcome-driven grid expansion.
- Latency/cost/depth claims must come from measured evidence or remain UNMEASURABLE.
- Historical wrappers may remain only when they delegate to the canonical implementation; no third concurrent implementation.

## Canonical map

| Requirement | Classification | Canonical surface / evidence | Remaining action |
| --- | --- | --- | --- |
| Causal/gap diagnostics | ALREADY_IMPLEMENTED | `src/hl_observer/backtesting/lead_lag_causal_diagnostics.py`, compatibility wrappers, dedicated causal diagnostics tests | Keep wrappers delegating; no duplicate engine |
| TRAIN-only multi-asset selection | ALREADY_IMPLEMENTED | `src/hl_observer/backtesting/lead_lag_multiasset_train.py` | Structural split required because architecture gate caps Python modules at 800 lines |
| Cross-asset leader→follower mapping | ALREADY_IMPLEMENTED | predeclared BTC/ETH leaders and fixed follower universe in `lead_lag_multiasset_train.py`; `tests/test_lead_lag_cross_asset_provenance.py` | Preserve fixed mapping and source-alignment rejection |
| Same-shard BIN_TRADE/HL provenance | CORRECTED | TRAIN tape keeps per-observation `source_id`, `TRADE_OBS`, `HL_BOOK_SOURCE_IDS`; residual replay uses deterministic common source | Preserve fail-closed behavior during refactor |
| Reference-price residual hypothesis | CORRECTED | `lead_lag_reference_residual.py` + `lead_lag_reference_residual_grid.py`; wired into TRAIN family with fixed beta/window/threshold/horizon/policy grid | Keep beta/as-of causal and TRAIN-only |
| Multiple testing | CORRECTED | `research_family_trial_count()` expands base family by the full residual grid before replay; `_score_report` applies family alpha/trial count | Do not regress to outcome-dependent trial counting |
| Measured runtime latency | ALREADY_IMPLEMENTED | `load_runtime_latency_evidence()` and measured replay path | Missing evidence must fail closed / remain unmeasurable |
| Executable L2/cost/capacity replay | ALREADY_IMPLEMENTED | measured replay consumes recorded HL L2 with bid/ask and top-level capacity | Preserve full cost accounting; no synthetic profitability claims |
| Placebo / effective-independence controls | ALREADY_IMPLEMENTED | `tests/test_lead_lag_effective_independence.py` and related Lead-Lag diagnostics | Re-run in final regression |
| Maker / queue claims | BLOCKED_UNLESS_MEASURABLE | queue replay code exists, but queue/maker conclusions are admissible only when the required microstructure evidence is measured | No promotion based on modeled-only queue priority |
| Architecture giant-file gate | BLOCKED | `lead_lag_multiasset_train.py` ≈935 lines, `lead_lag_queue_replay.py` ≈1015, `lead_lag_shadow_economics.py` ≈829; CI ceiling is 800 | Split by cohesive responsibility; no whitelist or raised ceiling |
| Historical +4 USD objective | HISTORICAL / NOT A DONE GATE | prior economic campaign context | Never use as H—T-41 technical completion criterion |

## Structural refactor contract

The first canonical extraction target is the TRAIN tape loader currently embedded in `lead_lag_multiasset_train.py`:

1. freeze wall-clock TRAIN ranges from recorded market windows;
2. read aligned BIN_TRADE and HL rows from the same source shard;
3. reject invalid/out-of-TRAIN/duplicate observations;
4. retain observable timestamps and `source_id` provenance per trade/book;
5. return deterministic sorted tapes plus split/provenance metadata;
6. keep the existing public `load_multiasset_train_tape(...)` interface as a compatibility wrapper.

The extraction is behavior-preserving. It must not change candidate grids, thresholds, costs, held-out access, freeze policy, paper/read-only state, or trial counting.

## Final H—T-41 review gate

H—T-41 can move to Review only when all of the following are evidenced on one exact SHA:

- all §11/776+ Lead-Lag requirements are mapped here to a canonical implementation or explicit classification;
- deterministic causal/provenance/cross-asset/residual/multiple-testing tests pass;
- oversized Lead-Lag modules owned by this lane comply with the existing architecture ceiling without whitelisting;
- relevant regression and repository safety/quality gates are green, or unrelated external failures are explicitly classified with evidence;
- no held-out leakage, economic retuning, real execution, or gate weakening was introduced.

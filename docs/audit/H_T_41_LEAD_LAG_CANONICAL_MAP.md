# H—T-41 — Lead-Lag canonical implementation map

Status: **TECHNICALLY COMPLETE / READY FOR REVIEW**  
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
| TRAIN-only multi-asset selection | CORRECTED | `src/hl_observer/backtesting/lead_lag_multiasset_train.py` plus extracted cohesive helpers from commit `71c81f31b70a3a074cb9ed68cae0cd794119bcce` | None for H—T-41 |
| Cross-asset leader→follower mapping | ALREADY_IMPLEMENTED | predeclared BTC/ETH leaders and fixed follower universe in the canonical multi-asset path; `tests/test_lead_lag_cross_asset_provenance.py` | Preserve fixed mapping and source-alignment rejection |
| Same-shard BIN_TRADE/HL provenance | CORRECTED | TRAIN tape keeps per-observation `source_id`, `TRADE_OBS`, `HL_BOOK_SOURCE_IDS`; residual replay uses deterministic common source | Preserve fail-closed behavior |
| Reference-price residual hypothesis | CORRECTED | `lead_lag_reference_residual.py` + `lead_lag_reference_residual_grid.py`; wired into TRAIN family with fixed beta/window/threshold/horizon/policy grid | Keep beta/as-of causal and TRAIN-only |
| Multiple testing | CORRECTED | `research_family_trial_count()` expands base family by the full residual grid before replay; `_score_report` applies family alpha/trial count | Do not regress to outcome-dependent trial counting |
| Measured runtime latency | ALREADY_IMPLEMENTED | `load_runtime_latency_evidence()` and measured replay path | Missing evidence must fail closed / remain unmeasurable |
| Executable L2/cost/capacity replay | ALREADY_IMPLEMENTED | measured replay consumes recorded HL L2 with bid/ask and top-level capacity | Preserve full cost accounting; no synthetic profitability claims |
| Placebo / effective-independence controls | ALREADY_IMPLEMENTED | `tests/test_lead_lag_effective_independence.py` and related Lead-Lag diagnostics | Preserve in regression |
| Maker / queue claims | BLOCKED_UNLESS_MEASURABLE | queue replay code exists, but queue/maker conclusions are admissible only when the required microstructure evidence is measured | No promotion based on modeled-only queue priority |
| Architecture giant-file gate | CORRECTED | `71c81f31b70a3a074cb9ed68cae0cd794119bcce` split `lead_lag_multiasset_train.py`, `lead_lag_queue_replay.py` and `lead_lag_shadow_economics.py` by cohesive responsibility; the later 32-shard pytest matrix passed all shards | No whitelist, no raised ceiling |
| Historical +4 USD objective | HISTORICAL / NOT A DONE GATE | prior economic campaign context | Never use as H—T-41 technical completion criterion |

## Structural refactor result

The structural extraction was completed without changing the public Lead-Lag contract. The large TRAIN, queue replay and shadow-economics modules were split into cohesive helpers while preserving:

1. frozen wall-clock TRAIN ranges from recorded market windows;
2. aligned BIN_TRADE and HL rows from the same source shard;
3. rejection of invalid/out-of-TRAIN/duplicate observations;
4. observable timestamps and `source_id` provenance per trade/book;
5. deterministic sorted tapes and split/provenance metadata;
6. compatibility of the existing public interfaces;
7. candidate grids, thresholds, costs, held-out access, freeze policy, paper/read-only state and trial counting.

## Final H—T-41 evidence

- `71c81f31b70a3a074cb9ed68cae0cd794119bcce` closes the three architecture-size blockers without exemptions.
- On later exact SHA `4c6152f8e3c97d2fe44bdcba6a4deabc29ef3f9c`, all 32 pytest shards of `coverage-parallel-probe` completed successfully. The remaining aggregate failure was the repository-wide coverage percentage witness, owned by H—T-50/H—T-21 rather than a Lead-Lag behavioral or architecture failure.
- Lead-Lag causal/provenance/cross-asset/reference-residual/multiple-testing tests are part of the repository test suite and therefore passed in that matrix.
- No real execution, held-out leakage, economic retuning, whitelist, skip/xfail or gate weakening was introduced.
- The technical Done contract remains independent of +4 USD / positive PnL.

H—T-41 is technically complete and may proceed to AgiFlow Review/Done. The repository-wide 100% coverage witness remains tracked separately by the CI owner lot.

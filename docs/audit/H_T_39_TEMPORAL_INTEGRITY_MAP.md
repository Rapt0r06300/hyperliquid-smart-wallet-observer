# H—T-39 — Temporal integrity / anti-faux-backtest evidence map

Scope: ROADMAP MD LOT 04, V5 §9. This receipt is about temporal correctness only; it intentionally defines no minimum PnL.

## Exact baseline

- Audited baseline before this receipt: `24b005fd46ff0c272cdd04d086fd3b611c10315a` (`main`).
- Golden temporal corpus landed in ancestor commit `31e59a84be33cbd379418670079c9b7400215b3b`.
- PAPER / READ-ONLY invariants remain unchanged.

## §9 mechanism map

| Requirement | Concrete implementation / proof | Fail-closed / negative evidence |
|---|---|---|
| Future Leakage Scanner | `src/hl_observer/testing/lookahead_detector.py` parses Python AST rather than grep and flags suspicious unwindowed temporal aggregates. | `tests/test_temporal_integrity_golden_corpus.py` deliberately feeds an unwindowed temporal aggregate and requires a LOOKAHEAD suspicion. |
| Differential Validation | `lit_le_futur()` in `src/hl_observer/testing/lookahead_detector.py` compares the same point on full vs causally truncated input and rejects material divergence. | Golden corpus requires a leaking global mean to be detected while a past-only expanding mean remains accepted. |
| Warmup / recursive stability | `src/hl_observer/backtesting/recursive_analysis.py` + `src/hl_observer/backtesting/recursive_bias_probe.py` compare full-history backtest values to the same timestamps computed with a bounded live buffer. | Probe returns non-stable / explicit reason when the comparable history is insufficient; recursive differences are measured rather than silently accepted. |
| Knowledge lookahead | `src/hl_observer/research/empirical_memory.py` exposes point-in-time evidence state and `require_revalidated_evidence(..., as_of=...)`. | Golden corpus proves evidence observed/revalidated after `as_of` is UNVERIFIABLE and raises `EmpiricalMemoryUnverifiedError`; past fresh evidence is accepted. |
| Golden Scenario Corpus | `tests/test_temporal_integrity_golden_corpus.py` is deterministic, small, public-contract based and covers positive + negative temporal scenarios. | Commit `31e59a84be33cbd379418670079c9b7400215b3b` adds the corpus without weakening an existing gate. |

## Family / execution-path coverage

### Copy-Vault

`src/hl_observer/backtesting/copy_vault_vnext_train.py` is explicitly TRAIN-only. Admission sorts by `signal_ts_ms`, inspects only `ordered[:index]`, requires `age > 0`, and calls the canonical entity-consensus gate with `as_of_ms=timestamp`. The module states that validation/OOS/forward outcomes are not consulted for selection. Existing tests include `tests/test_copy_vault_vnext_train.py` and related Copy-Vault regime/hypothesis tests.

Temporal claim: a Copy-Vault candidate cannot gain support from a later wallet observation at the same or future timestamp through this path.

### Lead-Lag

`tests/test_lead_lag_measured_replay.py` exercises causal-book behavior directly. Its fixtures distinguish a book immediately before the trigger from an executable book only after measured runtime latency; tests require stale books to wait for the next observation, verify the last causal book semantics, keep raw diagnostics non-certifying, and verify predeclared admission does not read the trade result.

Temporal claim: replay execution time and executable L2 are tied to observations available at or before the decision/execution boundary; outcome-driven admission is not allowed by the covered path.

### Cross-Venue

Cross-Venue certification requires point-in-time provenance rather than accepting legacy aggregate snapshots. `tests/test_cross_venue_economic_provenance.py` requires certified snapshots plus mapping proof, skew proof and the four-fill contract; an older atomic source without these proofs is explicitly rejected. OOS proof is also required to carry `no_lookahead=True`, and forward proof must be post-freeze.

Temporal claim: a Cross-Venue result without certifiable synchronization/provenance is economically ineligible rather than silently trusted.

### Replay / backtest / paper

The temporal contracts above are used on replay/backtest paths and the family certification layer. The Lead-Lag replay tests explicitly distinguish diagnostic-only observations from certified PnL. The repository remains PAPER / READ-ONLY; this lot introduces no real-order path.

### Knowledge / research

Empirical-memory evidence is evaluated at an explicit `as_of` boundary. Future evidence fails closed in the golden corpus, preventing research knowledge learned later from being silently treated as historically available.

## Differential / golden regression contract

The golden corpus intentionally contains both sides of the invariant:

1. causal transform accepted;
2. future-dependent transform rejected;
3. AST scanner flags a suspicious unwindowed temporal aggregate;
4. future-dated knowledge rejected fail-closed;
5. valid past knowledge accepted.

This makes a regression visible even if a future refactor preserves output shape but breaks chronology.

## CI classification at audited baseline

For `24b005fd46ff0c272cdd04d086fd3b611c10315a`, `hypersmart/security-quality` was SUCCESS. The repository-wide `coverage-parallel-probe` had all 32 shards successful but the final 100% aggregate ratchet was red. That general coverage debt is owned separately (H—T-21); it is not evidence of a failing H—T-39 temporal test and this lot does not lower or bypass the ratchet.

## Completion semantics

H—T-39 is complete only when this map and the golden corpus are both ancestors of the exact reviewed SHA and the task receipt records that SHA. No economic return threshold belongs to this lot.

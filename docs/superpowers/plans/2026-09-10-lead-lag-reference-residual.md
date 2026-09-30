# Lead-Lag Reference Residual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a causal, fail-closed reference-price residual primitive for Lead-Lag TRAIN research without creating a competing replay engine.

**Architecture:** Keep the transform in a focused module beside the canonical Lead-Lag backtesting code. The function consumes already-recorded observations, uses local `observable_at_ms` only, requires one aligned source across both assets/endpoints, and rejects beta estimates not known before the return window. It does not fit beta, tune thresholds, load heldout data, or execute trades.

**Tech Stack:** Python stdlib, pytest.

**Spec:** AgiFlow H—T-41 / V5 §11 Lead-Lag hardening.

## Global Constraints

- PAPER/read-only only; real execution remains false.
- No heldout/OOS data loaded by this transform.
- No retroactive threshold or beta fitting.
- No third Lead-Lag diagnostic/replay implementation.
- Fail closed on missing causal endpoints, invalid beta/window, or provenance mismatch.

---

### Task 1: Causal reference residual primitive

**Files:**
- Create: `src/hl_observer/backtesting/lead_lag_reference_residual.py`
- Test: `tests/test_lead_lag_reference_residual.py`

**Interfaces:**
- Consumes: sequences of mappings containing `observable_at_ms`, `price`, `source_id`; explicit `decision_ms`, `window_ms`, `beta`, `beta_asof_ms`.
- Produces: `compute_reference_residual(...) -> dict[str, Any]` with `OK` plus residual diagnostics or `UNMEASURABLE` plus a deterministic reason.

- [x] **Step 1: Write the failing test**

```python
result = compute_reference_residual(reference, follower, decision_ms=2000, window_ms=1000, beta=0.5, beta_asof_ms=900)
assert result["status"] == "OK"
assert result["max_observable_at_ms"] == 2000
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest -q tests/test_lead_lag_reference_residual.py`
Expected RED: import fails because `lead_lag_reference_residual` does not yet exist.

- [x] **Step 3: Write minimal implementation**

Implement endpoint selection at-or-before each causal cutoff, beta-as-of rejection, common-source enforcement, log-return residual in bps, and paper/read-only metadata.

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest -q tests/test_lead_lag_reference_residual.py`
Expected GREEN: `3 passed`.

- [ ] **Step 5: Wire into the predeclared TRAIN candidate grid only after the primitive lands and current ownership of `lead_lag_multiasset_train.py` is rechecked.**

This second step must preserve fixed trial counting, multiple-testing correction, and exact-shard provenance; it must not load heldout data or retune beta/thresholds from results.

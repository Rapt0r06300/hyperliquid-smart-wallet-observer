# Copy-Vault Hypothesis Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make killed Copy-Vault hypotheses machine-traceable and fail closed before the vNext research selector runs.

**Architecture:** Add a small Copy-Vault-only hypothesis registry that records immutable disposition metadata and rejects killed or unknown hypothesis IDs. Wire the active vNext selector through that guard in the existing research pack and emit the ledger in the TRAIN-only summary for exact-run evidence.

**Tech Stack:** Python 3, pytest, existing HyperSmart backtesting modules.

**Spec:** AgiFlow H—T-40 — ROADMAP MD LOT 05 / V5 §10 Copy-Vault hardening.

## Global Constraints

- `main` only; no persistent side branch.
- PAPER/READ-ONLY, 0 €, no real execution.
- Do not weaken tests, gates, economic thresholds, copyability, freshness, causal or held-out controls.
- A killed hypothesis must not become runnable merely by being referenced again.
- Unknown hypothesis IDs fail closed until explicitly registered and reviewed.

---

### Task 1: Copy-Vault hypothesis disposition registry

**Files:**
- Create: `src/hl_observer/backtesting/copy_vault_hypothesis_registry.py`
- Test: `tests/test_copy_vault_hypothesis_registry.py`

**Interfaces:**
- Produces: `copy_vault_hypothesis_disposition(hypothesis_id: str) -> dict[str, str]`
- Produces: `require_runnable_copy_vault_hypothesis(hypothesis_id: str) -> dict[str, str]`
- Produces: `copy_vault_hypothesis_ledger() -> list[dict[str, str]]`

- [ ] **Step 1: Write the failing tests**

```python
assert copy_vault_hypothesis_disposition("copy_vault_simple_whitelist")["status"] == "KILLED"
with pytest.raises(RuntimeError, match="KILLED"):
    require_runnable_copy_vault_hypothesis("copy_vault_simple_whitelist")
with pytest.raises(RuntimeError, match="UNREGISTERED"):
    require_runnable_copy_vault_hypothesis("copy_vault_future_unreviewed")
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest -q tests/test_copy_vault_hypothesis_registry.py`
Expected before implementation: import/module failure.

- [ ] **Step 3: Implement the minimal fail-closed registry**

Register the killed simple whitelist and the current causal multi-wallet consensus selector. Return copies of registry records and reject every status other than `ACTIVE`.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `python -m pytest -q tests/test_copy_vault_hypothesis_registry.py`
Expected: PASS.

### Task 2: Wire the registry into the vNext pack

**Files:**
- Modify: `src/hl_observer/backtesting/economic_vnext_pack.py`

**Interfaces:**
- Consumes: `MECHANISM` from `copy_vault_vnext_train`.
- Consumes: `require_runnable_copy_vault_hypothesis` and `copy_vault_hypothesis_ledger`.
- Produces: summary field `copy_vault_hypothesis_registry`.

- [ ] **Step 1: Guard the active selector before loading/running Copy-Vault raw research.**
- [ ] **Step 2: Persist active selector disposition plus the full family ledger in the TRAIN-only summary.**
- [ ] **Step 3: Run `python -m pytest -q tests/test_copy_vault_hypothesis_registry.py tests/test_economic_vnext_pack.py`.**
- [ ] **Step 4: Verify no certification/PnL/safety semantics changed, then commit one coherent unit.**

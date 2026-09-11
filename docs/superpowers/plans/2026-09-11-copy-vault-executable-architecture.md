# Copy-Vault Executable Architecture Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `copy_vault_executable.py` below the repository's 800-line architecture ceiling without changing Copy-Vault execution or economics.

**Architecture:** Extract only the pure observed-L2 side validation and VWAP walking helpers into a focused family-local module. `copy_vault_executable.py` remains the public orchestration surface and imports the extracted private helpers. No thresholds, gates, fee assumptions, causal timing, or paper/read-only semantics change.

**Tech Stack:** Python 3.11, pytest, existing `tests/test_copy_vault_executable.py` and `tests/test_invariants_architecture.py`.

**Spec:** `docs/audit/ROADMAP_V5_LOT05_COPY_VAULT_MAPPING.md`

## Global Constraints

- Branch: `main` only; no persistent side branch.
- Paper/read-only strict; no real execution.
- Do not raise the 800-line architecture ceiling and do not add a legacy exemption.
- Do not touch Lead-Lag giant files or shared/core ownership surfaces.
- Preserve canonical costs, capacity/liquidatability checks, causal timestamps, and TRAIN/OOS/forward separation.

---

### Task 1: Extract pure observed-L2 execution math

**Files:**
- Create: `src/hl_observer/backtesting/copy_vault_execution_math.py`
- Modify: `src/hl_observer/backtesting/copy_vault_executable.py`
- Test: `tests/test_copy_vault_executable.py`
- Test: `tests/test_invariants_architecture.py`

**Interfaces:**
- Consumes: observed book mappings and validated `(price, quantity)` levels.
- Produces: `_book_side(book, field, expected_best, descending)`, `_walk_quote_notional(levels, target_quote_usd)`, `_walk_base_quantity(levels, target_quantity)` with behavior identical to the pre-extraction implementation.

- [x] **Step 1: Establish RED**

Run on exact base `1b39f730b33c2f1a7cc49fd2e351f20f6eee868a`:

```bash
pytest tests/test_invariants_architecture.py::test_pas_de_nouveau_fichier_geant -q
```

Observed in CI: FAIL because `backtesting/copy_vault_executable.py` has 825 lines (>800). The same invariant also reports three Lead-Lag files; those are explicitly out of E2 scope.

- [ ] **Step 2: Extract the pure helpers**

Move the three helper implementations byte-for-byte in semantics to `copy_vault_execution_math.py`; import them back into `copy_vault_executable.py`. Do not modify `execute_metaorder()` logic.

- [ ] **Step 3: Run focused behavioral regression**

```bash
pytest tests/test_copy_vault_executable.py -q
```

Expected: PASS.

- [ ] **Step 4: Run architecture invariant**

```bash
pytest tests/test_invariants_architecture.py::test_pas_de_nouveau_fichier_geant -q
```

Expected: Copy-Vault no longer appears in the offender list. The test may remain red only because of separately-owned Lead-Lag files; that residual failure must be classified, not bypassed.

- [ ] **Step 5: Run relevant CI/regression and review diff**

Verify exact SHA workflows and ensure the diff changes no economic constants, cost formulas, causal gates, or safety flags.

- [ ] **Step 6: Commit and checkpoint AgiFlow**

Classify the Copy-Vault architecture gap `CORRIGÉ`; keep H—T-40 in Testing until its remaining acceptance/review evidence is satisfied.

## Self-review

- Spec coverage: extraction is architecture-only; existing §10/776+ economic and integrity mappings are preserved.
- Placeholder scan: none.
- Type consistency: helper signatures exactly match their pre-extraction call sites.

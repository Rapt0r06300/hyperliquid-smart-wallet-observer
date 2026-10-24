# CopyVault Pre-Backtest Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every official CopyVault simulation, replay, and backtest path fail closed on temporally impossible, non-finite, malformed, or out-of-scope inputs before any economic result can be emitted.

**Architecture:** Keep the existing single `src/hl_observer` engine and immutable V21 evaluator. Harden validation at the earliest shared boundaries (paper intents, book ingestion, causal feature extraction, executable replay) and make the official laboratory instantiate the canonical pipeline with every paused family explicitly disabled. Do not add a second engine, download data, run a real campaign, or touch AlinaSync/restoration state.

**Tech Stack:** Python 3, pytest, ruff, stdlib dataclasses/JSON/math, Windows CMD launchers.

**Spec:** `docs/reference/HYPERSMART_CANONICAL_SPEC.md`, `HYPERSMART_CONSTITUTION.md`, `LOIS_MESUREES.md`, `SECURITY.md`, `CLAUDE.md`.

**Global constraints:** PAPER/READ-ONLY, CopyVault is the only active economic family, missing is never zero, future observations are never fresh, all admitted numeric inputs are finite and positive where economically required, exact L2 and causal timestamps remain mandatory, no deletion or mutation of SAFE shards.

---

## Task 1: Harden canonical paper and runtime truth boundaries

**Files:**
- Modify: `src/hl_observer/ops/paper_canonique.py`
- Test: `tests/test_paper_canonique.py`

1. Add failing tests proving rejection of empty identities, non-positive/non-finite notionals, invalid timestamps, invalid liquidity quantities/prices, invalid maker inputs, future book ages, and future runtime events.
2. Run the focused tests and confirm the new cases fail for the intended reasons.
3. Add small shared numeric validators and fail-closed reasons/errors without changing valid outputs.
4. Run `pytest -q tests/test_paper_canonique.py` and confirm all pass.

## Task 2: Harden causal L2 ingestion and V21 feature extraction

**Files:**
- Modify: `src/hl_observer/backtesting/copy_vault_book_loader.py`
- Modify: `src/hl_observer/backtesting/copy_vault_v21_frozen.py`
- Test: `tests/test_copy_vault_executable.py`
- Test: `tests/test_copy_vault_v21_frozen.py`

1. Add failing tests for NaN/Infinity top-of-book fields, malformed/non-finite L2 depth, future reference books, and non-finite first-fill notionals.
2. Confirm RED on the focused tests.
3. Reject those rows before sorting, feature construction, capacity computation, or eligibility accounting; count invalid loader rows explicitly.
4. Run the two focused test modules and confirm GREEN.

## Task 3: Enforce CopyVault-only execution in the official laboratory

**Files:**
- Modify: `src/hl_observer/ops/lab_recherche.py`
- Modify: `src/hl_observer/ops/lab_alpha.py`
- Test: `tests/test_lab_recherche.py`
- Test: `tests/test_lab_alpha_e2e.py`
- Test: `tests/test_historical_analysis_launcher.py`

1. Add failing tests that the canonical replay constructs `MegaCablage` with Cross-Venue paper disabled and that the search space/cache no longer varies on paused-family parameters.
2. Confirm RED.
3. Remove the Cross-Venue parameter from the CopyVault search space, explicitly pass `cross_venue_paper=False`, keep report compatibility as a zero-valued diagnostic, and update stale documentation/comments.
4. Run the focused laboratory/scope tests and confirm GREEN.

## Task 4: Whole-path verification and audit record

**Files:**
- Modify only if a failing test proves a defect in the changed scope.

1. Run all CopyVault/vault tests, scope tests, lab launcher tests, simulation pipeline tests, and replay compatibility tests.
2. Run targeted ruff and Python bytecode compilation on changed modules.
3. Run the full test suite with fail-fast; classify any failure by reproducing it against the pre-change base before touching code.
4. Review the final diff against the canonical spec: causal time, exact inputs, fees/costs, paper-only, CopyVault-only, determinism, and honest proof labels.
5. Fetch/rebase safely if needed, rerun the focused gate on final HEAD, commit, and push `main` only after all relevant gates are green.

## Review Focus

- NaN/Infinity behavior in comparisons and hashes.
- Negative ages accidentally treated as fresh.
- Missing economic values silently coerced to zero.
- Paused families influencing search-space size, cache identity, fills, PnL, or promotion.
- Held-out/frozen parameters being altered after hash verification.
- Any path that can claim `PASS`, `eligible`, or `economically_proven` without causal exact-L2 evidence.
- Any change that could call a real exchange, network endpoint, or mutate/download SAFE shards.

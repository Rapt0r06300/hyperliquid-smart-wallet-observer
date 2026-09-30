# Copy-Vault Universe Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Copy-Vault universe coverage, survivorship and sybil/entity evidence explicit and fail-closed without duplicating existing wallet-integrity rules.

**Architecture:** Add one family-local adapter in `backtesting` that consumes the canonical `research.wallet_integrity` primitives. It only emits deterministic research evidence and eligibility; it cannot execute trades or certify economic edge.

**Tech Stack:** Python stdlib, pytest, existing `hl_observer.research.wallet_integrity`.

**Spec:** AgiFlow H—T-40 — Copy-Vault hardening technique complet.

## Global Constraints

- Paper/read-only; 0 € and no real execution.
- Reuse canonical wallet-integrity controls rather than clone their logic.
- Fail closed when universe coverage or sybil/entity normalization evidence is incomplete.
- Do not change costs, economic thresholds, held-out policy, CI gates or shared/core behavior.

---

### Task 1: Family-local universe integrity gate

**Files:**
- Create: `src/hl_observer/backtesting/copy_vault_universe_integrity.py`
- Test: `tests/test_copy_vault_universe_integrity.py`

**Interfaces:**
- Consumes: `correction_survivorship`, `detecter_sybils`, `inclure_wallets_liquides`.
- Produces: `evaluate_copy_vault_universe_integrity(...) -> dict[str, Any]`.

- [x] **Step 1: Write failing tests** for undeclared universe, survivor outside universe, incomplete cohort coverage and unresolved sybil normalization.
- [x] **Step 2: Verify RED**: four tests fail because the family-local module is absent.
- [x] **Step 3: Implement minimal gate** with normalized wallet IDs, explicit reasons and canonical helper reuse.
- [x] **Step 4: Verify GREEN**: four targeted tests pass locally against the fetched canonical wallet-integrity behavior.
- [ ] **Step 5: Verify repository CI** on the exact pushed SHA before promoting H—T-40 beyond In Progress.

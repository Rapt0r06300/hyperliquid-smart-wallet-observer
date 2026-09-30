# Copy-Vault Behavioral Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire existing wallet behavioral fingerprints into Copy-Vault vNext integrity so related/fake-leader wallets cannot be counted as independent evidence when entity normalization contradicts behavioral evidence.

**Architecture:** Keep the control family-local in `copy_vault_vnext_integrity.py` and reuse `research.wallet_fingerprint` rather than duplicating fingerprint logic. Behavioral evidence is deterministic and PAPER/READ-ONLY; when supplied and complete it must fail closed if a detected related-wallet group is split across declared entities. Existing universe/survivorship/correlation checks remain unchanged.

**Tech Stack:** Python 3, pytest, existing `hl_observer.research.wallet_fingerprint` primitives.

**Spec:** AgiFlow H—T-40 / roadmap V5 §10 + Copy-Vault 776+ hardening.

## Global Constraints

- `main` is the only persistent branch.
- PAPER/READ-ONLY only; 0 real execution.
- Do not weaken costs, causality, held-out, concentration, multiple-testing, CI, or safety gates.
- Reuse existing controls and implement only the proven gap.

---

### Task 1: Prove the missing behavioral-entity gate

**Files:**
- Modify: `tests/test_copy_vault_vnext_integrity.py`

**Interfaces:**
- Consumes: `evaluate_copy_vault_vnext_integrity(copy_raw)`.
- Produces: a failing regression proving behaviorally related wallets cannot remain distinct declared entities.

- [ ] **Step 1: Write the failing test**

Add a case with two wallets having matching fill cadence/coin fingerprints while `entity_groups` declares different entities. Assert `eligible is False` and reason `BEHAVIORAL_ENTITY_NORMALIZATION_MISSING`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_copy_vault_vnext_integrity.py`
Expected before implementation: new test FAIL because current vNext integrity ignores behavioral fingerprint evidence.

### Task 2: Wire the existing fingerprint primitive

**Files:**
- Modify: `src/hl_observer/backtesting/copy_vault_vnext_integrity.py`
- Modify: `tests/test_copy_vault_vnext_integrity.py`

**Interfaces:**
- Consumes: `wallet_fingerprint.fingerprint`, `wallet_fingerprint.entites_communes`, declared `entity_groups`, optional `behavioral_fingerprint` evidence.
- Produces: `behavioral_fingerprint` audit evidence plus fail-closed reason when detected related-wallet groups are not normalized consistently.

- [ ] **Step 1: Implement minimal adapter**

Normalize wallet IDs, reject malformed supplied behavioral evidence, compute fingerprints from supplied wallet fills, derive related groups, and compare each related group with declared entity IDs.

- [ ] **Step 2: Preserve backward compatibility**

Do not make behavioral evidence mandatory when absent in legacy payloads; when it is supplied, malformed/incomplete evidence fails closed.

- [ ] **Step 3: Run targeted tests**

Run: `pytest -q tests/test_copy_vault_vnext_integrity.py tests/test_wallet_fingerprint.py`
Expected: PASS.

- [ ] **Step 4: Review and regression**

Run: `python -m py_compile src/hl_observer/backtesting/copy_vault_vnext_integrity.py` plus relevant Copy-Vault regression/CI. Verify no shared/core, Lead-Lag, Cross-Venue, cost, threshold, or safety gate changes.

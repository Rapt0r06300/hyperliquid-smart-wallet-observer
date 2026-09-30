# Copy-Vault H—T-40 Final Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining H—T-40 evidence-mapping gap without changing economic thresholds or reopening held-out data.

**Architecture:** Treat current Copy-Vault family-local modules and tests as the implementation source of truth. Add one auditable mapping document that classifies each §10/776+ control as implemented, corrected, historical/killed, or still blocked, and only change code if a concrete unmapped gate is proven.

**Tech Stack:** Python 3, pytest, GitHub Actions, Markdown evidence ledger.

**Spec:** AgiFlow H—T-40 — roadmap V5 §10 + Copy-Vault 776+ hardening.

## Global Constraints

- `main` only; PAPER/READ-ONLY; 0 EUR real execution.
- Do not change economic thresholds, costs, test gates, CI gates, or another lane's surfaces.
- +4 USD / positive PnL is not a Done condition for this technical roadmap lot.
- Preserve train/OOS/forward separation and family-local evidence; no shared proof across strategy families.
- Preserve killed hypotheses as historical negative evidence and fail closed on unknown hypotheses.

---

### Task 1: Build the exact §10/776+ Copy-Vault control map

**Files:**
- Create: `docs/audit/ROADMAP_V5_LOT05_COPY_VAULT_MAPPING.md`

**Interfaces:**
- Consumes: `copy_vault_vnext_train.py`, `copy_vault_vnext_integrity.py`, `copy_vault_universe_integrity.py`, `copy_vault_hypothesis_registry.py`, Copy-Vault tests, and `economic_vnext_pack.py`.
- Produces: a human- and machine-reviewable evidence checkpoint for H—T-40.

- [ ] **Step 1: Map hypothesis lifecycle and killed-history controls**

Record the simple whitelist as `KILLED/HISTORICAL`, the causal multi-wallet consensus as current `ACTIVE`, and the registry fail-closed behavior for unregistered hypotheses.

- [ ] **Step 2: Map false-leader/entity/survivorship controls**

Record public-entity normalization, behavioral fingerprint normalization, sybil correlation evidence, complete-universe coverage, survivor coverage, and liquidated-wallet cohort evidence with their exact tests.

- [ ] **Step 3: Map copyability/economic/causal controls**

Record `liquidatable_net`, full cost reconciliation, entry/exit capacity, causal lag ceilings, metaorder de-duplication, and strictly-prior consensus evidence.

- [ ] **Step 4: Map concentration/multiple-testing/held-out controls**

Record coin/entity concentration ceilings, fixed-grid trial accounting, TRAIN-only selection, `heldout_evaluated=False`, and physical-freeze gating.

- [ ] **Step 5: Self-review the map**

Verify every H—T-40 acceptance criterion has at least one concrete code path and one test/evidence reference; classify any genuine gap instead of inventing coverage.

### Task 2: Verify exact-SHA evidence and update AgiFlow

**Files:**
- No production changes unless Task 1 proves a missing gate.

**Interfaces:**
- Consumes: current `main` SHA and GitHub Actions status.
- Produces: exact-SHA review evidence for H—T-40.

- [ ] **Step 1: Re-read `main` after the mapping commit**

Confirm no concurrent commit touched the mapped Copy-Vault surfaces.

- [ ] **Step 2: Inspect CI status**

Do not claim global green if an unrelated coverage workflow remains red; distinguish H—T-40 family evidence from repository-wide CI debt.

- [ ] **Step 3: Update AgiFlow acceptance criteria conservatively**

Check only criteria directly proven by code/tests/mapping. Move H—T-40 through Testing/Review/Done only if all criteria are evidenced; otherwise keep it In Progress with the remaining blocker named exactly.

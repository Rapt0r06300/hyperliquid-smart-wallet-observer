# Copy-Vault Proof Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make exact Copy-Vault checkpoints single-writer and quarantine every metaorder affected by a duplicated checkpoint before any economic replay.

**Architecture:** The campaign checkpoint companion is the sole bound-checkpoint writer and persists its state. `userfills-live` keeps unbound WS L2 collection but disables its duplicate bound-checkpoint scheduler. The loader pre-scans valid checkpoint bindings, quarantines whole metaorders on duplicate IDs, and returns explicit audit counts.

**Tech Stack:** Python 3.11+, pytest, JSONL causal receipts, Windows-compatible process supervision.

**Spec:** `docs/superpowers/specs/2026-09-08-economic-proof-vnext.md`

## Global Constraints

- Each module must independently prove at least 4 USD liquidatable net PnL on every proof day.
- Never aggregate PnL across families.
- Duplicated Copy-Vault checkpoint ID quarantines the entire metaorder.
- TRAIN selects; validation confirms; OOS remains sealed until freeze.
- Paper/read-only only: zero real orders, money, private keys, signatures, deposits, or withdrawals.
- Preserve unrelated working-tree changes.

---

### Task 1: Whole-metaorder duplicate quarantine

**Files:**
- Modify: `src/hl_observer/backtesting/copy_vault_book_loader.py:24-208`
- Test: `tests/test_copy_vault_executable.py`

**Interfaces:**
- Consumes: JSONL checkpoint rows with `checkpoint_id` and `metaorder_id`.
- Produces: `load_observed_books(...)` with audit keys `duplicate_checkpoint_ids`, `duplicate_checkpoint_rows`, `quarantined_checkpoint_metaorders`, and `quarantined_checkpoint_rows`.

- [ ] **Step 1: Write the failing duplicate-quarantine test**

Create two valid rows with `checkpoint_id="mo-bad:ENTRY"`, add another unique
stage for `mo-bad`, and one valid row for `mo-good`. Assert that no row from
`mo-bad` appears, `mo-good` remains, and the four new counters equal `1`, `1`,
`1`, and `3` respectively.

- [ ] **Step 2: Verify the test fails for the current first-row-wins behavior**

Run: `python -m pytest tests/test_copy_vault_executable.py -k duplicate_checkpoint -vv`

Expected: FAIL because one `mo-bad` row is still returned and the audit keys do
not exist.

- [ ] **Step 3: Implement a two-pass causal checkpoint loader**

Parse causal rows into validated candidates first. Count `checkpoint_id`
occurrences, derive the set of affected `metaorder_id` values, then call the
existing row-admission path only for non-quarantined candidates. Keep ordinary
unbound WS deduplication unchanged. Return exact counters from the census.

- [ ] **Step 4: Verify focused and neighboring loader tests**

Run: `python -m pytest tests/test_copy_vault_executable.py tests/test_copy_vault_book_loader_import.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hl_observer/backtesting/copy_vault_book_loader.py tests/test_copy_vault_executable.py
git commit -m "Quarantaine les checkpoints Copy-Vault dupliques"
```

### Task 2: Single bound-checkpoint writer

**Files:**
- Modify: `tools/collecter_userfills_vaults.py:1664-1743`
- Modify: `src/hl_observer/ops/collecteur_registry.py:76-89`
- Modify: `src/hl_observer/simulation/economic_collection_plan.py:193-213,291-299`
- Test: `tests/test_collector_lease.py`
- Test: `tests/test_economic_collection_plan.py`

**Interfaces:**
- Consumes: collector registry and heartbeat protocol map.
- Produces: campaign state in which `copy-vault-checkpoints` is the only bound-checkpoint writer while `userfills-live` remains the live-fill and unbound-L2 source.

- [ ] **Step 1: Write failing ownership tests**

Add a registry test asserting every collector declares a
`copy_vault_checkpoint_role` and exactly one campaign-required collector has
role `BOUND_WRITER`. Add a collection-plan test asserting simultaneous bound
writers yield `CHECKPOINT_WRITER_CONFLICT` and `running_collector_protocol_ready
is False`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_collector_lease.py tests/test_economic_collection_plan.py -k "checkpoint and (writer or role or conflict)" -vv`

Expected: FAIL because roles and the conflict state do not exist.

- [ ] **Step 3: Implement explicit ownership**

Declare `userfills-live` as `UNBOUND_SOURCE` and the campaign companion as
`BOUND_WRITER`. Disable `_new_metaorder_checkpoints` scheduling in
`userfills-live`; keep `_append_copy_vault_book` for unbound `HYPERLIQUID_L2_WS`
rows. Make the economic collection plan fail closed if more than one active
collector advertises `BOUND_WRITER`.

- [ ] **Step 4: Verify collector tests**

Run: `python -m pytest tests/test_collector_lease.py tests/test_economic_collection_plan.py tests/test_copy_vault_checkpoint_tail.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/collecter_userfills_vaults.py src/hl_observer/ops/collecteur_registry.py src/hl_observer/simulation/economic_collection_plan.py tests/test_collector_lease.py tests/test_economic_collection_plan.py
git commit -m "Impose un seul redacteur de checkpoints Copy-Vault"
```

### Task 3: Clean-epoch verification and campaign replay

**Files:**
- Modify: `src/hl_observer/backtesting/copy_vault_protocol.py`
- Modify: `src/hl_observer/collection/copy_vault_checkpoint_tail.py`
- Modify: `src/hl_observer/backtesting/copy_vault_book_loader.py`
- Modify: `src/hl_observer/backtesting/copy_vault_executable.py`
- Modify: `src/hl_observer/simulation/economic_campaigns.py`
- Modify: `src/hl_observer/simulation/economic_objective.py`
- Test: `tests/test_copy_vault_checkpoint_tail.py`
- Test: `tests/test_copy_vault_executable.py`
- Test: `tests/test_economic_campaigns.py`
- Test: `tests/test_economic_objective.py`
- Test: `tests/test_economic_proof_audit.py`

**Interfaces:**
- Consumes: loader duplicate-quarantine counters and collector ownership state.
- Produces: campaign refusal reason `COPY_CHECKPOINT_INTEGRITY_NOT_CLEAN` until a post-owner-election clean epoch has zero duplicate IDs.

- [ ] **Step 1: Write the failing proof-gate test**

Feed a Copy-Vault campaign an audit with a quarantined checkpoint metaorder and
no clean-epoch receipt. Assert that the family cannot report `ATTEINT` and emits
`COPY_CHECKPOINT_INTEGRITY_NOT_CLEAN`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_economic_objective.py -k checkpoint_integrity -vv`

Expected: FAIL because the proof gate is absent.

- [ ] **Step 3: Add the integrity proof gate**

Migrate the companion state to a new clean epoch, bind every new checkpoint to
the elected writer run ID, propagate that binding into executable trades, and
require all OOS/forward proof trades to use non-quarantined checkpoint rows at
or after that epoch. Preserve the OOS seal and existing family separation.

- [ ] **Step 4: Verify Copy-Vault and proof suites**

Run: `python -m pytest tests/test_copy_vault_checkpoint_tail.py tests/test_copy_vault_executable.py tests/test_economic_objective.py tests/test_economic_proof_audit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hl_observer/backtesting/copy_vault_protocol.py src/hl_observer/collection/copy_vault_checkpoint_tail.py src/hl_observer/backtesting/copy_vault_book_loader.py src/hl_observer/backtesting/copy_vault_executable.py src/hl_observer/simulation/economic_campaigns.py src/hl_observer/simulation/economic_objective.py tests/test_copy_vault_checkpoint_tail.py tests/test_copy_vault_executable.py tests/test_economic_campaigns.py tests/test_economic_objective.py tests/test_economic_proof_audit.py
git commit -m "Bloque la preuve Copy-Vault hors epoque propre"
```

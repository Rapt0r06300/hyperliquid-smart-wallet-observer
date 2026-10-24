# SAFE L2 Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local SAFE L2 certification compact, resumable, and authoritative for snapshot backtests versus continuous replays without changing source shards.

**Architecture:** Keep `tools/certify_local_l2.py` as the single verifier. Store detailed results as compressed JSONL, publish only atomic summary metadata in the main report, and record SHA-bound per-use admissions in AlinaSync's existing `SAFE_SHARDS.sqlite3`. Reuse whole unchanged venue/symbol groups for cross-shard resume; rescan a complete group whenever any member changes.

**Tech Stack:** Python 3 stdlib, SQLite, gzip, pytest, Windows CMD wrapper.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

## Global Constraints

- PAPER / READ-ONLY / FAIL-CLOSED; never modify canonical source shards.
- CopyVault is the only active economic family.
- Only exact SHA-256/size-bound SAFE catalog rows may be admitted.
- Missing or blocked L2 evidence is never fabricated or promoted.
- Reuse the existing certifier and AlinaSync database; create no second restoration or replay engine.

## Review Focus

- A changed group member must invalidate the entire cross-shard cache group.
- An interrupted run must leave L2 database views unavailable rather than expose stale admission.
- `SNAPSHOT_OBSERVATIONS_ONLY` must never enter the continuous-replay view.
- A Gate REST anchor must be authenticated by recorded provenance and native ID, never inferred from deltas.
- Compact output must retain detailed reasons and repair proofs without embedding unbounded segment arrays in the summary.

---

### Task 1: Compact, use-specific L2 evidence

**Files:**
- Modify: `tools/certify_local_l2.py`
- Modify: `tests/test_certify_local_l2.py`

**Interfaces:**
- Produces: atomic `LOCAL_L2_CERTIFICATION.json`, compressed `LOCAL_L2_CERTIFICATION_ROWS.jsonl.gz`, and `_L2AdmissionRegistry` views for snapshot/backtest and continuous/replay use.

- [ ] Write failing tests for compact output, strict use-class separation, interrupted-run fail-closed state, and exact SHA binding.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Implement deterministic compressed detail output and transactional SQLite admission.
- [ ] Run the focused tests and confirm they pass.
- [ ] Commit the task.

### Task 2: Safe cross-shard resume and native Gate anchors

**Files:**
- Modify: `tools/certify_local_l2.py`
- Modify: `tests/test_certify_local_l2.py`
- Modify: `VERIFIER_REPARER_L2_LOCAL.cmd`

**Interfaces:**
- Consumes: Task 1 compact row records.
- Produces: SHA/stat-bound compressed group receipts and authenticated Gate REST-to-WS continuity.

- [ ] Write failing tests for unchanged group reuse, changed-member invalidation, and Gate REST anchor recognition.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Implement whole-group cache reuse and authenticated Gate anchor parsing; enable `--resume --cross-shard` in the wrapper.
- [ ] Run the focused tests and confirm they pass.
- [ ] Commit the task.

### Task 3: Surface honest AlinaSync counts and lock the contract

**Files:**
- Modify: `tools/sync_complete_clone.py`
- Modify: `tests/test_sync_complete_clone.py`
- Modify: `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

**Interfaces:**
- Consumes: Task 1 SQLite views/meta.
- Produces: explicit L2 snapshot-backtestable, continuous-replayable, blocked, and certification-state fields in sync summaries.

- [ ] Write failing tests proving generic SAFE counts are not presented as L2 continuity proof.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Implement read-only L2 summary extraction and document the canonical per-use admission contract.
- [ ] Run focused tests, then the full repository suite.
- [ ] Verify the final diff, security invariants, HEAD, and commit history.

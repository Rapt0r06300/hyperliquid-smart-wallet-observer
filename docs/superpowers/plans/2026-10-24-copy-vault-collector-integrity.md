# CopyVault Collector Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate silent CopyVault collector evidence loss and make replay admission fail closed whenever causal checkpoints are incomplete.

**Architecture:** Keep the existing bot collectors and bounded checkpoint companion. Add explicit bounded-queue admission, durable rotation/gap counters, heartbeat quality metrics, and make the existing replay loader consume those counters before accepting a clean checkpoint epoch.

**Tech Stack:** Python standard library, asyncio, pytest, Windows collector launcher.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

## Global Constraints

- PAPER / READ-ONLY / FAIL-CLOSED; no order path or private credential.
- Preserve raw observed timestamps and source truth; never interpolate missing evidence.
- Reuse the bot's existing collectors and replay loader; no second collector engine.
- Do not stop, restart, or reconfigure a running collector on the user's PC.
- Publish source changes only to the single repository `main`.

## Review Focus

- File replacement/truncation must be detected without treating old bytes as new evidence.
- Queue saturation must be explicit and must retain already scheduled checkpoints.
- An expired, dropped, or rotation-affected checkpoint epoch must never remain replay-admissible.
- User-fill persistence must continue even when the derived L2 tape queue is saturated.
- Git publishing must not hydrate or stage raw shard/runtime directories.

---

### Task 1: Fail-closed causal checkpoint collector

**Files:**
- Modify: `src/hl_observer/collection/copy_vault_checkpoint_tail.py`
- Modify: `tools/collecter_copy_vault_checkpoints.py`
- Modify: `src/hl_observer/backtesting/copy_vault_book_loader.py`
- Test: `tests/test_copy_vault_checkpoint_tail.py`
- Test: `tests/test_launcher_core_heartbeat_bridge.py`

- [ ] Write failing tests for rotation recovery, bounded queue overflow, heartbeat gap metrics, and replay-receipt refusal.
- [ ] Run the focused tests and observe the expected failures.
- [ ] Implement explicit counters, bounded all-or-none checkpoint scheduling, rotation recovery, and fail-closed receipt admission.
- [ ] Run the focused tests and confirm green.
- [ ] Commit the task.

### Task 2: Expose derived L2 tape loss in the main bot collector

**Files:**
- Modify: `tools/collecter_userfills_vaults.py`
- Test: `tests/test_collecter_userfills_vaults.py`
- Test: `tests/test_launcher_core_heartbeat_bridge.py`

- [ ] Write a failing test proving a full L2 tape queue is counted while the source fill remains durably appended.
- [ ] Run the focused test and observe the expected failure.
- [ ] Count tape drops separately and include them in the existing critical-gap heartbeat metric.
- [ ] Run collector and readiness tests and confirm green.
- [ ] Commit the task.

### Task 3: Publishing and regression gate

**Files:**
- Verify: `POUSSER-GITHUB-FORCE.cmd`
- Verify: `tools/push_github_safe.ps1`
- Test: `tests/test_push_github_safe_contract.py`
- Test: `tests/test_push_github_launcher.py`

- [ ] Prove the push helper skips LFS hydration and raw runtime/data/datasets/archive content.
- [ ] Run all CopyVault collector, replay-loader, heartbeat, and push-contract tests.
- [ ] Verify compile, diff, security invariants, local HEAD, remote HEAD, and publish with a normal non-force push.

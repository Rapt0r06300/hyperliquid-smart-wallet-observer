# Git Sync Exact Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local Git synchronizer reliably preserve every admissible local code change, retrieve concurrent GitHub `main` work, publish without force-push, and prove local `HEAD` equals GitHub `main` at the end.

**Architecture:** Keep the existing fail-closed synchronizer and protected runtime/data boundary. Add a single remote-snapshot helper that reuses the local tracking ref when its SHA already matches the freshly observed GitHub SHA, otherwise performs one bounded fetch. Increase only the network fetch budgets needed by this repository, then retain the existing checkpoint, replay, race verification, and final SHA checks.

**Tech Stack:** Python 3.10+, Git for Windows, pytest, Windows CMD launcher.

**Spec:** User requirement from this task: local admissible changes, including one-byte edits, must be sent; concurrent GitHub work must be recovered; no force-push, reset, clean, shard download, data deletion, or worktree.

## Global Constraints

- Work directly in `C:\Users\flo\Desktop\Projet invest`; never create or use a worktree.
- Never force-push, reset, clean, delete data, or download shards.
- Preserve the existing protected `runtime`, dataset, archive, secret, and binary safety boundary.
- Finish only when local `HEAD` and `refs/heads/main` on GitHub are the same SHA, or emit a fail-closed report naming the blocker.

## Review Focus

- A remote SHA equal to the local tracking ref must not trigger a needless slow fetch; test `test_preflight_reuses_matching_tracking_remote_without_fetch`.
- A remote SHA different from the tracking ref must still fetch before comparison; cover through the existing divergence tests and the real launcher run.
- A one-byte tracked source edit must be checkpointed and published; retain the existing `test_single_byte_source_change_is_committed_and_published`.
- A local branch promotion must remain fast-forward-only; retain `test_non_main_branch_is_promoted_by_fast_forward_only`.
- A fetch that exceeds the large-repository budget must fail closed without a push; retain timeout tests and verify the real timeout budget is 300 seconds.

### Task 1: Remote snapshot reuse and fetch budget

**Files:**
- Modify: `tools/alina_git_code_sync.py:66-90, 1163-1235, 1251-1295`
- Test: `tests/test_alina_git_code_sync.py:817-860`

**Interfaces:**
- Produces: `Synchronizer._fetch_remote_snapshot(observed_remote: str) -> str`, returning the SHA used for preflight comparison and recording whether the tracking ref was reused.

- [ ] **Step 1: Write the failing test**

Change the local-ahead preflight test to require zero fetch commands when `refs/remotes/origin/main` already equals the fresh `ls-remote` SHA, and add an assertion that the report records snapshot reuse.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `tools/python/python.exe -m pytest -q tests/test_alina_git_code_sync.py::test_local_ahead_reuses_fast_path_fetch_for_preflight`

Expected: FAIL because the current implementation always fetches during `capture_preflight`.

- [ ] **Step 3: Implement the minimal helper and timeout change**

Set the bounded repository fetch budgets to 300 seconds. Implement `_fetch_remote_snapshot` to compare the observed GitHub SHA with `refs/remotes/origin/main`; reuse the tracking ref when equal, otherwise run the existing non-tag fetch with the new budget. Route `capture_preflight` and the clean fast path through this helper without changing checkpoint or protected-path rules.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `tools/python/python.exe -m pytest -q tests/test_alina_git_code_sync.py::test_local_ahead_reuses_fast_path_fetch_for_preflight`

Expected: PASS with no fetch command and the local branch still published to the test remote.

- [ ] **Step 5: Run the synchronizer regression slice**

Run: `tools/python/python.exe -m pytest -q tests/test_alina_git_code_sync.py`

Expected: All tests in the file pass; any unrelated timeout must be reported by test name.

### Task 2: Real local-to-GitHub parity run

**Files:**
- Execute: `POUSSER-GITHUB-FORCE.cmd --promote-current-to-main`
- Verify: `runtime/reports/git-sync/LAST_SYNC.json`

**Interfaces:**
- Consumes: Task 1’s remote snapshot logic and existing checkpoint/replay/publish flow.
- Produces: `status=SYNCHRONIZED`, `push_completed=true` when local work exists, and equal final local/GitHub SHAs.

- [ ] **Step 1: Run the launcher with the explicit promotion option**

Run from the repository root with `HYPERSMART_PUSH_NO_PAUSE=1`. The launcher must checkpoint all admissible tracked and source changes, integrate the current GitHub `main`, and use only a normal push.

- [ ] **Step 2: Verify the receipt and remote SHA**

Run `git rev-parse HEAD` and `git ls-remote origin refs/heads/main`; require equality. Read `runtime/reports/git-sync/LAST_SYNC.json`; require `status=SYNCHRONIZED`, `force_push=false`, `reset_or_clean=false`, and `shard_downloads=false`.

- [ ] **Step 3: Verify the final worktree state**

Run `git status --short --branch` and `git diff --check`. Report protected runtime/data files separately if they remain intentionally local and excluded by policy.


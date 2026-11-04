# POUSSER-GITHUB-FORCE Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POUSSER-GITHUB-FORCE.cmd` a faster, measurable, fail-closed code synchronizer that never force-pushes or touches protected data.

**Delivery target:** Implement and verify 20 robust corrective improvements, grouped across the seven tasks below, with repeated real CMD runs near the end.

**Architecture:** Keep the CMD as a thin, hash-pinned launcher and extend the existing Python synchronizer in place. Optimize the local Git inventory with cached bounded pathspecs, separate local/network budgets, and reuse of proven SHAs; add structured receipts and narrow safety checks instead of introducing a second orchestration layer.

**Tech Stack:** Windows CMD, PowerShell 5+/7, Python 3.10+, Git 2.54 portable/system Git, pytest, JSON receipts.

**Spec:** `docs/POUSSER-GITHUB-FORCE-HARDENING-DESIGN.md`

## Global Constraints

- No force-push, reset, clean, stash, deletion of data, or shard download.
- Canonical repository remains `Rapt0r06300/hyperliquid-smart-wallet-observer` on `main`.
- Runtime remains PAPER / READ-ONLY / FAIL-CLOSED.
- No new dependency, service, worktree, or parallel orchestration architecture.
- `datasets` remains outside the full local worktree scan; any incoming remote protected path is checked by targeted comparison before merge.
- The CMD must preserve double-click behavior and return the synchronizer exit code.

## Review Focus

- A 1.9M-path protected dataset must not restore the old 30-second `git status` timeout; the benchmark test must pin the bounded inventory path.
- A timed-out Git process tree must be fully gone before the receipt says `NO_GO`; the Windows descendant test must assert this.
- Credentials in Git URLs or stderr must be redacted before console/receipt output; the redaction test must inspect both fields.
- A remote race or transient network error may retry, but authentication, branch protection, and invalid remote errors must stop without repeated push attempts; classifier tests must pin the counts.
- A successful push must be supported by a parsed porcelain ref result and exact `ls-remote` SHA equality; the push verification test must fail closed on either missing proof.

## File Map

- Modify `tools/alina_git_code_sync.py`: performance pathspec cache, latency budgets, process cleanup proof, error redaction/classification, push verification, receipts, and capability checks.
- Modify `POUSSER-GITHUB-FORCE.cmd`: expose the new plan/diagnostic options, preserve hash pinning, and propagate exit codes/receipt paths.
- Modify `tests/test_alina_git_code_sync.py`: deterministic regression, failure-mode, and push/receipt tests.
- Create `tools/benchmark_git_sync.py`: read-only five-run benchmark for local inventory and portable self-check, emitting JSON only to stdout.
- Modify `docs/POUSSER-GITHUB-FORCE-HARDENING-DESIGN.md`: record measured implementation results and any accepted exception.

### Task 1: Establish a repeatable performance baseline

**Files:**
- Create: `tools/benchmark_git_sync.py`
- Test: `tests/test_alina_git_code_sync.py`

**Interfaces:**
- Produces `benchmark_git_sync.main(argv: Sequence[str]) -> int`.
- Emits JSON fields `runs`, `warmup_seconds`, `inventory_seconds`, `inventory_p50_seconds`, `inventory_p95_seconds`, `git_commands`, and `mutations`.

- [ ] **Step 1: Write the failing benchmark contract test**

  Add `test_benchmark_is_read_only_and_reports_p50_p95` using a disposable test repository and assert five measured runs, `mutations == []`, and numeric p50/p95 fields.

- [ ] **Step 2: Run the focused test and verify it fails**

  Run: `tools\python\python.exe -m pytest tests/test_alina_git_code_sync.py -q -k benchmark_is_read_only`

  Expected: FAIL because `tools/benchmark_git_sync.py` does not exist.

- [ ] **Step 3: Implement the read-only benchmark**

  Use the existing `Synchronizer` inventory path with a fake/local Git runner in tests; never call `add`, `commit`, `fetch`, `merge`, `push`, `reset`, `clean`, or `stash`.

- [ ] **Step 4: Run the focused test and verify it passes**

  Run the same command; expected PASS.

- [ ] **Step 5: Run the real checkout benchmark**

  Run: `tools\python\python.exe tools\benchmark_git_sync.py --root . --runs 5`

  Expected: JSON with no mutations, local inventory p95 below 5 seconds after one warmup run.

### Task 2: Remove redundant local Git work and separate budgets

**Files:**
- Modify: `tools/alina_git_code_sync.py: constants, Synchronizer.__init__, command, _inventory, _pathspecs`
- Test: `tests/test_alina_git_code_sync.py`

**Interfaces:**
- Add `Synchronizer._pathspecs(include_protected: bool) -> tuple[str, ...]` with per-run caching.
- Add `Synchronizer._timed_phase(name: str, budget_seconds: float)` as a context manager that records duration and budget outcome in `report["phases"]`.

- [ ] **Step 1: Write failing tests for pathspec caching and phase metrics**

  Add `test_pathspecs_are_cached_per_run` and `test_phase_metrics_record_duration_and_budget`, asserting one filesystem enumeration and numeric duration/budget fields.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `tools\python\python.exe -m pytest tests/test_alina_git_code_sync.py -q -k 'pathspecs_are_cached or phase_metrics'`

- [ ] **Step 3: Implement cached pathspecs and phase budgets**

  Cache the sorted tuple; keep `datasets` excluded from full worktree scans; use `--no-renames` for the bounded inventory; preserve targeted protected-path comparisons and the existing historical relocation checks.

- [ ] **Step 4: Add the clean-path Git-call budget**

  Reuse inventory and already proven remote SHA values; do not repeat `ls-remote`, status, or pathspec construction in the same phase unless a race invalidates the cache.

- [ ] **Step 5: Run focused tests and the real benchmark**

  Expected: focused tests PASS, no mutation commands, and at least 20% fewer Git commands on the clean path compared with the baseline receipt.

### Task 3: Harden timeout and process-tree cleanup

**Files:**
- Modify: `tools/alina_git_code_sync.py:_terminate_process_tree, _run_git, command`
- Test: `tests/test_alina_git_code_sync.py`

**Interfaces:**
- Add `_remaining_process_ids(root: Path, parent_pid: int) -> list[int]` for post-kill verification.
- Record `timed_out`, `killed_process_tree`, and `residual_process_ids` in the Git command receipt.

- [ ] **Step 1: Add failing Windows cleanup assertions**

  Extend `test_terminate_process_tree_kills_descendant_process` to assert the parent and child are absent after cleanup; add a timeout receipt test requiring an empty residual list.

- [ ] **Step 2: Run focused tests and verify the new assertions fail**

  Run: `tools\python\python.exe -m pytest tests/test_alina_git_code_sync.py -q -k 'terminate_process_tree or timeout_receipt'`

- [ ] **Step 3: Implement postcondition verification**

  Kill with `taskkill /T /F`, wait for pipes with `communicate`, poll the process tree, and fail closed if any descendant remains; never continue to Git mutation after an unproven cleanup.

- [ ] **Step 4: Run focused cleanup tests**

  Expected: PASS on Windows; non-Windows tests remain skipped only where the repository already marks them Windows-specific.

### Task 4: Add redaction and failure classification

**Files:**
- Modify: `tools/alina_git_code_sync.py:_run_git, command, publish`
- Test: `tests/test_alina_git_code_sync.py`

**Interfaces:**
- Add `_redact_sensitive_text(value: str) -> str`.
- Add `_classify_git_failure(stderr: str, returncode: int) -> Literal["retryable_race", "retryable_network", "auth", "protected", "configuration", "unknown"]`.

- [ ] **Step 1: Write failing redaction and retry-classification tests**

  Add tests with `https://user:token@example.com`, `ghp_...`, `github_pat_...`, `Authorization: Bearer ...`, non-fast-forward, authentication, branch-protection, and DNS failures; assert the output class and retry decision.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `tools\python\python.exe -m pytest tests/test_alina_git_code_sync.py -q -k 'redact or classify_git_failure'`

- [ ] **Step 3: Implement redaction at the report boundary**

  Apply redaction before `say`, exception construction, JSON serialization, and push stderr persistence; never log raw environment values or remote credentials.

- [ ] **Step 4: Implement bounded class-specific retries**

  Retry only remote races and explicitly transient network errors; stop immediately for authentication, protection, invalid remote, malformed output, and unknown failures.

- [ ] **Step 5: Run focused tests and inspect a negative receipt**

  Expected: no secret substring remains and non-retryable failures have exactly zero extra push attempts.

### Task 5: Make push proof explicit and capability checks fail early

**Files:**
- Modify: `tools/alina_git_code_sync.py:preflight, publish, report initialization`
- Modify: `POUSSER-GITHUB-FORCE.cmd:help and option dispatch`
- Test: `tests/test_alina_git_code_sync.py`

**Interfaces:**
- Add `_verify_git_capabilities() -> None` for required commands/options and portable version floors.
- Add `_verify_push_porcelain(output: str, expected_sha: str, expected_ref: str) -> None`.
- Add receipt fields `run_id`, `launcher_sha256`, `engine_sha256`, `git_version`, `python_version`, `push_ref_result`.

- [ ] **Step 1: Write failing capability and push-proof tests**

  Add tests for missing capability, wrong ref, missing porcelain success, and exact remote SHA mismatch; assert `NO_GO` and no false `SYNCHRONIZED` status.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `tools\python\python.exe -m pytest tests/test_alina_git_code_sync.py -q -k 'capabilit or push_porcelain or remote_sha_mismatch'`

- [ ] **Step 3: Implement preflight capability verification**

  Validate Git/Python versions, canonical remote, branch, engine build/hash, and required Git command behavior before any add/commit/push mutation.

- [ ] **Step 4: Implement structured push verification**

  Invoke `git push --porcelain`, parse the single `main` ref result, then call `ls-remote` and require exact SHA equality before declaring success.

- [ ] **Step 5: Add the explicit no-mutation plan contract**

  Keep `--dry-run` as the plan mode, print the command classes that would be allowed, and assert no add/commit/fetch/merge/push in its report.

- [ ] **Step 6: Run focused tests and the portable self-check**

  Run: `tools\python\python.exe -m pytest tests/test_alina_git_code_sync.py -q -k 'capabilit or push_porcelain or dry_run'` and `POUSSER-GITHUB-FORCE.cmd --portable-self-check`.

### Task 6: Add immutable run receipts and bounded retention

**Files:**
- Modify: `tools/alina_git_code_sync.py:_write_report, run`
- Modify: `POUSSER-GITHUB-FORCE.cmd:finish output`
- Test: `tests/test_alina_git_code_sync.py`

**Interfaces:**
- Add `_new_run_id() -> str`.
- Write `runtime/reports/git-sync/history/RUN-<run_id>.json` atomically and update `LAST_SYNC.json` atomically.
- Keep at most 30 historical sync receipts; never delete reports outside that exact directory.

- [ ] **Step 1: Write failing receipt and retention tests**

  Add `test_receipt_has_run_id_and_retention_is_bounded`, asserting atomic files, stable `LAST_SYNC.json`, max 30 historical files, and no deletion outside the report directory.

- [ ] **Step 2: Run focused tests and verify they fail**

  Run: `tools\python\python.exe -m pytest tests/test_alina_git_code_sync.py -q -k 'receipt_has_run_id'`

- [ ] **Step 3: Implement atomic historical receipts**

  Use `NamedTemporaryFile` in the exact report directory, `os.replace`, stable JSON schema, and deterministic retention ordering by filename/run timestamp.

- [ ] **Step 4: Add latency and mutation summaries**

  Record per-phase p50/p95 only when a benchmark run provides multiple samples; for a normal sync record exact duration and mutation list.

- [ ] **Step 5: Run focused receipt tests**

  Expected: PASS, with failure receipts written even when Git mutation is refused.

### Task 7: Complete launcher integration and full verification

**Files:**
- Modify: `POUSSER-GITHUB-FORCE.cmd`
- Modify: `tests/test_alina_git_code_sync.py`
- Modify: `docs/POUSSER-GITHUB-FORCE-HARDENING-DESIGN.md`

- [ ] **Step 1: Add launcher contract tests**

  Assert help text documents `--dry-run`, `--wip-only`, `--portable-self-check`, exit-code propagation, the current engine hash, and the absence of force/reset/clean/stash commands.

- [ ] **Step 2: Run the full dedicated suite**

  Run: `tools\python\python.exe -m pytest tests/test_alina_git_code_sync.py -q`

  Expected: all tests pass, including the Windows process-tree tests.

- [ ] **Step 3: Run static and syntax checks**

  Run: `tools\python\python.exe -m py_compile tools/alina_git_code_sync.py` and the repository’s configured Ruff check if available.

- [ ] **Step 4: Run five real read-only benchmarks**

  Run: `tools\python\python.exe tools\benchmark_git_sync.py --root . --runs 5`

  Expected: p95 local inventory under 5 seconds, no mutation list entries, and no full `datasets` scan.

- [ ] **Step 5: Run the actual launcher in `--dry-run` and inspect receipts**

  Run: `POUSSER-GITHUB-FORCE.cmd --dry-run` with pause disabled only for automation; verify no local HEAD or remote SHA changes and no force/reset/clean/stash/shard operation.

- [ ] **Step 6: Update the design note with measured results**

  Record actual p50/p95, Git command count reduction, test count, and any failed acceptance criterion. Do not claim success if a criterion is not measured.

## Self-review

- Spec coverage: all 11 design objectives map to Tasks 1–7; all non-objectives are repeated in Global Constraints.
- Speed coverage: Tasks 1–2 and 7 measure cold/warm inventory latency, phase budgets, and Git-call reduction.
- Safety coverage: Tasks 3–6 cover process cleanup, redaction, retry classification, push proof, and receipts.
- Scope risk: no task changes trading/runtime behavior, protected data content, GitHub workflows, dependencies, or worktree layout.

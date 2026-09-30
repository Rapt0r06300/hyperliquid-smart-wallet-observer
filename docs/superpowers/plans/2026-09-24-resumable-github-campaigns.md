# Resumable GitHub-Hosted Campaigns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task in the current session. Do not use a local or self-hosted runner.

**Goal:** Continue collectors, replays, backtests, and daily per-module net-PnL proofs across bounded GitHub-Hosted jobs using durable Dataset V2 checkpoints.

**Architecture:** The main repository provides a deterministic campaign state machine, CLI, adapters, and safety validation. Dataset V2 stores canonical manifests and immutable release assets, and owns a scheduled controller plus a dispatch-only worker. Existing schedules create deterministic campaigns instead of starting untracked long jobs; the controller leases and dispatches due work without recursive workflow chaining.

**Tech Stack:** Python 3.11/3.12, dataclasses/JSON, pytest, GitHub Actions, `gh` CLI, Dataset V2 GitHub Releases.

**Spec:** `docs/superpowers/specs/2026-09-24-resumable-github-campaigns-design.md`

## Global constraints

- Work only on both repositories' `main` branches and re-read their current heads before each publish.
- GitHub Hosted only; reject executable `self-hosted` jobs.
- Paper-only, read-only, no real order, no authenticated/private exchange endpoint.
- Dataset V2 is canonical; legacy dataset workflows remain disabled.
- Never upgrade `PARTIAL`, `UNAVAILABLE`, or `REJECT` to `SAFE` without exact evidence.
- Pin third-party Actions by full commit SHA.
- Use bounded attempts, total runtime, chunks, expiry, no-progress count, and backoff.
- Preserve Hyperliquid, Binance, Bybit, OKX, Gate, and Bitget.
- Make the smallest coherent commits: protocol in main, orchestration in Dataset V2, then rollout fixes only if CI exposes them.

---

### Task 1: Campaign contract and fail-closed state machine

**Main repository files:**
- Create: `src/hl_observer/control_plane/resumable_campaign.py`
- Create: `tests/test_resumable_campaign.py`

**Interfaces:**
- `CampaignManifest.from_dict()` and `to_dict()`
- `validate_manifest()`
- `transition()`
- `work_unit_id()`
- `complete_work_unit()`
- constants for active/terminal states and seven campaign kinds

- [ ] Write tests for the complete `alina.resumable_campaign.v1` contract, safety flags, allowed transitions, terminal immutability, deterministic unit IDs, idempotent completion, checksum collision, and status honesty.
- [ ] Run `pytest -q tests/test_resumable_campaign.py` and confirm the expected import failure.
- [ ] Implement immutable-value normalization, canonical JSON/SHA-256 helpers, validation, and the transition table.
- [ ] Require pinned code/config/work-plan digests and `paper_only=true`, `read_only=true`, `real_execution=false`.
- [ ] Reject unknown fields that affect execution, invalid time ordering, unsafe flags, and a `SAFE` output whose evidence status is not `SAFE`.
- [ ] Re-run the targeted tests to green.

### Task 2: Leases, retry classification, deadlines, and due-work selection

**Main repository files:**
- Modify: `src/hl_observer/control_plane/resumable_campaign.py`
- Modify: `tests/test_resumable_campaign.py`

**Interfaces:**
- `acquire_lease()` / `verify_lease()` / `release_lease()`
- `classify_failure()`
- `mark_continuation()` / `mark_terminal()`
- `select_due_campaigns()`
- `StopLimits`

- [ ] Add failing tests for active and expired leases, stale tokens, duplicate dispatch, transient retry/backoff, permanent quality failure, no-progress cutoff, max-attempt/chunk/runtime cutoff, absolute expiry, and soft deadline.
- [ ] Implement a hashed random lease token; never serialize the plaintext token.
- [ ] Make schema/digest/safety/provenance/data-quality failures non-retryable.
- [ ] Make only explicit infrastructure and temporary external-service classes retryable.
- [ ] Ensure a stale worker is a verified no-op and cannot advance a cursor.
- [ ] Run `pytest -q tests/test_resumable_campaign.py` to green.

### Task 3: Atomic campaign CLI for Dataset V2 Git worktrees

**Main repository files:**
- Create: `tools/resumable_campaign.py`
- Create: `tests/test_resumable_campaign_cli.py`

**CLI commands:**
- `create`
- `validate`
- `list-due`
- `acquire-lease`
- `record-unit`
- `continue`
- `finish`
- `fail`

- [ ] Write failing subprocess tests using a temporary `catalog/campaigns` directory.
- [ ] Test deterministic create/no-op, canonical newline-terminated JSON, optimistic expected-digest checks, lease output through `GITHUB_OUTPUT`, and refusal to overwrite a changed manifest.
- [ ] Implement atomic temporary-file replacement locally; Git commit/push conflict handling remains in the workflow.
- [ ] Ensure output never includes secrets or the plaintext lease token except the one masked workflow output needed by the current job.
- [ ] Run `pytest -q tests/test_resumable_campaign.py tests/test_resumable_campaign_cli.py` to green.

### Task 4: Bounded adapters for all seven campaign kinds

**Main repository files:**
- Create: `src/hl_observer/control_plane/campaign_adapters.py`
- Create: `tools/run_resumable_campaign.py`
- Create: `tests/test_resumable_campaign_adapters.py`
- Modify only as needed: `tools/collect_cloud_window.py`
- Modify only as needed: `tools/collect_cloud_copy_vault.py`
- Modify only as needed: `tools/collect_official_archives.py`
- Modify only as needed: `tools/collect_event_intelligence_v2.py`

**Interfaces:**
- `AdapterContext`
- `AdapterResult`
- `run_one_unit()`
- adapters for the four collection kinds, replay, backtest, and PnL proof

- [ ] Write failing tests with fake subprocess runners for command construction, soft-deadline refusal, immutable result digests, and honest result mapping.
- [ ] Keep work units bounded and deterministic; never call a live-order or private endpoint.
- [ ] For market continuations, assign a fresh `connection_id` and carry the previous boundary as provenance only.
- [ ] Preserve receive-wall timestamp, monotonic timestamp, per-connection sequence, gaps, resync, duplicate detection, trade reconciliation, instrument metadata, and funding fields.
- [ ] Treat a missing exact reference as `UNAVAILABLE`/`PARTIAL`, never as matched.
- [ ] Add subprocess timeouts and terminate cleanly before the worker soft deadline.
- [ ] Run the three campaign test files to green.

### Task 5: Deterministic replay/backtest merge and SAFE-only module PnL proof

**Main repository files:**
- Create: `src/hl_observer/control_plane/module_pnl_proof.py`
- Create: `tests/test_module_pnl_proof_campaign.py`
- Modify: `src/hl_observer/control_plane/campaign_adapters.py`
- Modify: `tests/test_resumable_campaign_adapters.py`
- Reuse: `src/hl_observer/ops/v2_dataset_bridge.py`
- Reuse: `tools/run_economic_objective_campaigns.py`

**Modules:**
- `copy_vault`
- `lead_lag`
- `cross_venue_dislocation_v2`
- `arbitrage` as its own reported unit while preserving canonical family mapping and preventing double counting

- [ ] Write failing tests proving that replay/backtest finalization requires every planned unit and matching input/output digests.
- [ ] Write failing tests proving that PnL proof rejects non-SAFE input, reports gross PnL, fees, slippage, funding/financing, net PnL, sample size, and independent verdicts.
- [ ] Explicitly reject cross-module subsidy and duplicate economic attribution between arbitrage aliases.
- [ ] Label the `$4/day/module` value as a threshold, never as guaranteed profit.
- [ ] Allow non-SAFE research diagnostics only with `proof_of_pnl=false`.
- [ ] Run targeted campaign, Dataset V2 reader, and economic objective tests to green.

### Task 6: Main-repository workflow governance and documentation

**Main repository files:**
- Modify: `tests/test_repository_governance.py`
- Modify: `tests/test_ci_supply_chain_pinning.py`
- Create: `tests/test_resumable_campaign_repository_policy.py`
- Modify: `README.md`

- [ ] Add tests asserting the campaign tooling has no real-execution surface and recognizes all six venues.
- [ ] Add a repository-wide executable-job policy that rejects `self-hosted` and workflow timeouts at or above 360 minutes.
- [ ] Verify disabled legacy/self-hosted files remain non-executable and do not wake a PC.
- [ ] Document the controller/worker model, honest statuses, and emergency disable procedure.
- [ ] Run `ruff check` on new Python files and the focused test set.

### Task 7: Dataset V2 campaign policy tests and fixtures

**Dataset V2 repository files:**
- Create: `tests/test_resumable_campaign_workflows.py`
- Create: `tests/fixtures/campaigns/continuation-required.json`
- Modify: `tests/test_workflow_bounds.py`
- Modify: `tests/test_dataset_policy.py`
- Modify: `.gitignore` only if generated transient state needs exclusion

- [ ] Rebase a clean Dataset V2 worktree on its current `origin/main`; do not overwrite automatic catalog commits.
- [ ] Write failing tests requiring controller/worker workflows, pinned actions, hosted labels, sub-six-hour timeouts, concurrency, minimal permissions, no recursive dispatch, and bounded inputs.
- [ ] Assert workers check out the main repository by manifest-pinned SHA with `persist-credentials: false`.
- [ ] Assert campaign manifests are the only durable mutable control-plane state and release assets are digest-addressed.
- [ ] Run `pytest -q tests/test_resumable_campaign_workflows.py tests/test_workflow_bounds.py tests/test_dataset_policy.py` and retain the expected red result before implementation.

### Task 8: Dataset V2 controller and worker workflows

**Dataset V2 repository files:**
- Create: `.github/workflows/resumable-campaign-controller.yml`
- Create: `.github/workflows/resumable-campaign-worker.yml`
- Create: `tools/commit_campaign_state.sh`
- Modify: `tests/test_resumable_campaign_workflows.py`

**Controller behavior:** validate, lease, commit with bounded rebase retry, dispatch once.

**Worker behavior:** validate lease, checkout pinned main SHA, run bounded units until soft deadline, publish immutable assets, checkpoint/finish, commit with bounded rebase retry.

- [ ] Implement the controller at an off-peak scheduled minute plus manual dispatch.
- [ ] Use one global controller concurrency group and one dynamic per-campaign worker group, both with `cancel-in-progress: false`.
- [ ] Set worker hard timeout to 345 minutes and application soft deadline to at most 315 minutes.
- [ ] Mask the lease token immediately and scope write permissions to the jobs that need them.
- [ ] Use bounded five-attempt fast-forward/rebase publishing; on unresolved conflict leave the prior manifest valid and fail visibly.
- [ ] Use `gh workflow run resumable-campaign-worker.yml` with same-repository `GITHUB_TOKEN`; workers never dispatch workers.
- [ ] Upload ordinary Actions artifacts for diagnostics only; publish durable result/checkpoint assets to releases and store their SHA-256 references.
- [ ] Run the Dataset V2 focused tests to green.

### Task 9: Campaign creators and collector schedule migration

**Dataset V2 repository files:**
- Create: `.github/workflows/create-resumable-campaigns.yml`
- Modify: `.github/workflows/collect-market-data-v2.yml`
- Modify: `.github/workflows/collect-copy-vault-v2.yml`
- Modify: `.github/workflows/collect-official-archives-v2.yml`
- Modify: `.github/workflows/collect-event-intelligence-v2.yml`
- Modify: `tests/test_workflow_bounds.py`
- Modify: `tests/test_resumable_campaign_workflows.py`

- [ ] Add failing tests for deterministic schedule-bucket campaign IDs and prevention of duplicate scheduled collection.
- [ ] Freeze market/copy-vault selections before campaign creation and store their digest plus bounded per-lane configuration.
- [ ] Create one child campaign per existing parallel lane so continuation remains single-lease while existing parallelism is preserved.
- [ ] Route the four existing schedules through campaign creation; keep manual diagnostic dispatch but remove duplicate scheduled execution paths.
- [ ] Create replay once per eligible SAFE dataset generation and pinned code/config tuple.
- [ ] Create daily four-module PnL-proof work, and allow bounded manual/scheduled backtest creation.
- [ ] Keep official-archive external failures honest and bounded; do not retry a deterministic `NO_ARCHIVE_EVENTS` as if it were transient.
- [ ] Run all Dataset V2 tests to green.

### Task 10: Forced two-chunk integration test and publication

**Main repository files:**
- Create: `tests/test_resumable_campaign_integration.py`

**Dataset V2 repository files:**
- Modify: `tests/test_resumable_campaign_workflows.py`
- Modify: `README.md`
- Modify: `docs/STORAGE_ARCHITECTURE.md`

- [ ] Simulate chunk 1 -> `CONTINUATION_REQUIRED`, an expired lease, chunk 2 -> `COMPLETE`, and duplicate dispatch -> no-op.
- [ ] Simulate a checksum mismatch and a quality rejection and prove neither is retried or promoted.
- [ ] Run focused main tests, then relevant collector/replay/PnL/governance tests.
- [ ] Run the complete Dataset V2 test suite and `tools/check_dataset_quality.py`.
- [ ] Commit and publish the main-repository implementation to the current `main` head without force.
- [ ] Rebase Dataset V2 on its latest automatic catalog head, commit orchestration, and publish to `main` without force.
- [ ] Manually dispatch a short two-chunk GitHub-Hosted smoke campaign; inspect every job log and manifest transition.
- [ ] Confirm a fresh `connection_id`, gap/resync/reconciliation fields, digest-addressed assets, and honest SAFE/PARTIAL/REJECT output.

### Task 11: Full CI observation and closure

**No code changes unless a real failure is identified.**

- [ ] On the main final SHA, inspect all jobs for: `collector-replay-integrity-ci`, `native-venues-github-validation`, gates 001-320, `security-quality`, `hyperlab-ci`, `labo-continu-ci`, `alpha-factory`, `hypersmart-ci`, `coverage-parallel-probe`, and `portable-release-windows`.
- [ ] On the Dataset V2 final SHA, inspect `dataset-quality-ci`, the four collection workflows, controller/worker smoke, release publication, and catalog indexing.
- [ ] Open logs from every red job and group failures by root cause before editing.
- [ ] Fix code regressions; update only tests that are demonstrably obsolete; never lower safety or data-quality gates.
- [ ] Treat the existing coverage fusion shortfall separately from functional shard failures; do not lower its 100% threshold merely to obtain green.
- [ ] If an external venue/service is unavailable, preserve exact evidence and status instead of fabricating success.
- [ ] Verify final remote heads, clean publication, campaign states, and absence of any executable self-hosted runner.

## Completion report

Return only after useful work is exhausted and all current functional reds are resolved. Report: final heads, important files, green workflow count, strictly external blockers with evidence, Dataset V2 collection state, and explicit confirmation that no collector or runner ran on the user's PC.

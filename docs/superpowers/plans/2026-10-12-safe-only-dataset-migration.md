# SAFE-only Dataset Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the bot stable, guarantee complete fresh-clone and incremental recovery of its certified working set (SAFE market data, module evidence, replay/backtest/OOS/forward results, economic outputs and recovery control records), publish only eligible payloads, then migrate history without losing verified evidence.

**Architecture:** The existing Dataset V2 publisher partitions every qualified bundle into an immutable SAFE data plane and a payload-free diagnostic register. The canonical restore builds a fixed certified working-set inventory spanning SAFE inputs, authoritative control state and provenance-bound derived results. A separate manual, resumable migration tool inventories historical Releases, repacks mixed containers, proves complete working-set parity, and permits deletion only against the exact frozen inventory digest.

**Tech Stack:** Python 3.11+, pytest, stdlib `json`/`hashlib`/`zipfile`, GitHub CLI/API on GitHub-hosted runners, GitHub Actions YAML.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md` — section “2026-10-12 — SAFE-only source publication and historical compaction”.

## Global Constraints

- Repository `Rapt0r06300/hyperliquid-smart-wallet-observer`, branch `main`, existing architecture only.
- COLLECT remains active; do not change phase/epoch or interrupt collectors.
- GitHub-hosted only; no self-hosted runner, user PC, retired data repository or Git LFS.
- PAPER / READ-ONLY / FAIL-CLOSED; no order, key, signature, deposit, withdrawal or real execution.
- Heavy payload eligibility is exactly `quality_status == "SAFE"` and `replay_compatible is True`.
- Fresh clone and existing-checkout update must restore the complete Git-tracked bot and 100% of the fixed SAFE/replayable catalog before any destructive cleanup is enabled.
- `REPLAY_READY_COMPLETE` covers the entire fixed certified working-set inventory by artifact class, not raw market shards alone.
- Diagnostic registers contain no market payload and can never become replay/backtest input.
- No deletion before remote replacement verification, exact SAFE parity and frozen-inventory SHA-256 confirmation.
- Dry-run is default; destructive execution is explicit, manual, bounded, checkpointed and resumable.
- The +5 USD net/day target is an honest per-family research threshold, never a promised outcome.

## Review Focus

- A manifest marked SAFE but missing `replay_compatible=true`, including a zero-eligible run, must remain diagnostic-only and create no misleading data Release; Tasks 1–2 pin this.
- A compacted ZIP mixing SAFE and non-SAFE members must retain byte-identical SAFE members and no others; Task 4 pins this.
- Remote inventory drift between planning and deletion must stop before the first delete; Task 5 pins this.
- A completed-looking capsule whose canonical SAFE asset is missing or hash-mismatched must be kept; Task 4 pins this.
- Interrupted clone hydration or a dirty tracked checkout must resume safely or fail without overwrite; Task 3 pins this.

## 2026-10-13 execution constraint

The preservation handoff supersedes every destructive step in Tasks 4–7 for
the current mission. Historical PARTIAL, REJECT, STALE, mixed containers and
recovery capsules remain non-consumable but preserved. Inventory, verification,
SAFE-only repacking and dry-run planning remain allowed; remote or local
deletion does not. A future deletion would require a new explicit user
authorization after a real fresh-clone and incremental-update proof reaches
exact working-set parity with sufficient disk. This is not such a proof.

---

### Task 1: Partition publication inputs and build a payload-free quality register

**Files:**
- Modify: `tools/publish_dataset_v2_release.py`
- Test: `tests/test_publish_dataset_v2_release.py`

**Interfaces:**
- Produces: `partition_publishable_manifests(manifests: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]`.
- Produces: `write_quality_register(root: Path, rejected: list[Mapping[str, Any]]) -> Path | None` writing `QUALITY_REJECTIONS.json.gz` with schema `alina.dataset_quality_rejections.v1`.
- Consumers: Tasks 2 and 3 use the eligible list and register identity.

- [ ] **Step 1: Write failing tests** proving SAFE+replay-compatible rows are eligible; SAFE without explicit replay compatibility, PARTIAL, REJECT and unknown rows are diagnostic-only; the register contains identity/status/reasons/provenance/counts/bytes/SHA but no local path or payload.
- [ ] **Step 2: Run tests to verify failure:** `python -m pytest -q tests/test_publish_dataset_v2_release.py -k 'partition or quality_register'`; expect missing interfaces/failing assertions.
- [ ] **Step 3: Implement the two interfaces** with deterministic ordering, canonical gzip metadata, strict field allow-listing and an invariant that every diagnostic row has `validation_allowed=false` and `replay_compatible=false`.
- [ ] **Step 4: Run the targeted tests** and expect PASS.
- [ ] **Step 5: Commit:** `git commit -m "feat(dataset): partition SAFE publication inputs"`.

### Task 2: Make canonical publication and recovery capsules SAFE-only

**Files:**
- Modify: `tools/publish_dataset_v2_release.py`
- Modify: `tools/recover_dataset_v2_capsules.py`
- Modify: `.github/workflows/resumable-campaign-worker.yml`
- Test: `tests/test_publish_dataset_v2_release.py`
- Test: `tests/test_recover_dataset_v2_capsules.py`
- Test: `tests/test_workflow_bounds.py`

**Interfaces:**
- Consumes: Task 1 partition and quality-register interfaces.
- Produces: `publish_bundle(...)` uploads only eligible payloads; `publish_quality_receipt(...) -> dict[str, Any]` handles zero-SAFE and mixed runs.
- Preserves: existing `publish_recovery_capsule(...)` signature while passing it a filtered index/manifests only.

- [ ] **Step 1: Write failing tests** proving no non-SAFE asset reaches `build_compacted_assets`, direct upload or recovery tar; a zero-SAFE run uploads only `QUALITY_REJECTIONS.json.gz` plus a terminal receipt; capsule recovery refuses legacy non-SAFE payload promotion.
- [ ] **Step 2: Run tests to verify failure:** `python -m pytest -q tests/test_publish_dataset_v2_release.py tests/test_recover_dataset_v2_capsules.py -k 'safe_only or zero_safe or recovery'`.
- [ ] **Step 3: Wire partitioning before `publish_recovery_capsule` and upload planning**, create a control-only Release for zero-SAFE runs, and make recovery reapply current eligibility instead of trusting the old capsule label.
- [ ] **Step 4: Update the hosted worker contract** so the diagnostic receipt is durable and no new workflow or schedule is introduced.
- [ ] **Step 5: Run targeted publisher/recovery/workflow tests** and expect PASS.
- [ ] **Step 6: Commit:** `git commit -m "feat(dataset): publish SAFE payloads only"`.

### Task 3: Lock stable complete clone and incremental-update recovery

**Files:**
- Modify: `tools/restore_alina.py`
- Modify: `tools/sync_complete_clone.py`
- Modify: `tests/test_restore_alina.py`
- Modify: `tests/test_sync_complete_clone.py`
- Modify: `tests/test_restore_alina_launcher.py`

**Interfaces:**
- Consumes: Task 2 SAFE-only Release/control layout.
- Preserves: `ALINA_SYNC_COMPLETE.cmd` and `bash ALINA_SYNC_COMPLETE.sh` as the canonical user entry points.
- Produces: `build_certified_working_set(...) -> dict[str, Any]` classifying raw SAFE data, module artifacts, replay/backtest/OOS/forward outputs, scoreboards/equity curves, control records and published snapshots.
- Produces: `REPLAY_READY_COMPLETE` only for exact fixed-inventory working-set parity; `RESTORE_INCOMPLETE` otherwise.

- [ ] **Step 1: Write failing working-set tests** requiring exact dataset-selection/code/config provenance for derived artifacts; valid positive and negative economic results are retained, while incomplete, corrupt, superseded or unbound outputs are excluded with explicit reasons.
- [ ] **Step 2: Write failing integration tests** simulating fresh clone, first hydration, interruption, Range resume, no-op rerun, new Release arrival, incremental hydration, dirty tracked checkout, unknown local files, corrupt cached assets and every required artifact class.
- [ ] **Step 3: Run tests to verify failure:** `python -m pytest -q tests/test_restore_alina.py tests/test_sync_complete_clone.py tests/test_restore_alina_launcher.py -k 'working_set or fresh or incremental or resume or dirty or corrupt'`.
- [ ] **Step 4: Implement `build_certified_working_set` and the minimum restore/sync changes** while preserving fast-forward-only Git updates, exact outer/member/chunk verification and local-file protection.
- [ ] **Step 5: Extend `RESTORE_REPORT.json`** with required/restored/verified/missing/corrupt/excluded counts and bytes for collections, module data, replays, backtests, OOS, forward-paper, economics, scoreboards, control records and snapshots.
- [ ] **Step 6: Add a deletion interlock** consumed by Task 5: no migration execute mode unless the same inventory digest has a passing fresh-clone/incremental recovery proof for every required artifact class.
- [ ] **Step 7: Run the complete three-file recovery suite** and expect PASS with explicit failure codes for every incomplete class.
- [ ] **Step 8: Commit:** `git commit -m "feat(recovery): restore complete certified working set"`.

### Task 4: Build deterministic historical inventory and SAFE-only repacking

**Files:**
- Create: `tools/migrate_safe_only_releases.py`
- Create: `tests/test_migrate_safe_only_releases.py`

**Interfaces:**
- Produces: `build_inventory(releases, catalog_rows, *, inspect_asset) -> dict[str, Any]` with canonical `inventory_sha256` and dispositions `KEEP_SAFE`, `REPACK_MIXED`, `DELETE_NON_SAFE`, `DELETE_REDUNDANT_CAPSULE`, `KEEP_UNIQUE_RECOVERY`.
- Produces: `repack_mixed_asset(source: Path, rows: list[Mapping[str, Any]], destination: Path) -> dict[str, Any]`.
- Produces: CLI `--repository`, `--catalog`, `--output`, `--checkpoint`, `--dry-run` (default).
- Consumers: Task 5 executes a frozen plan; Task 6 invokes the CLI.

- [ ] **Step 1: Write failing inventory tests** for all five dispositions, duplicate/ambiguous members, missing digest, path traversal, symlinks, mixed containers, completed and unique recovery capsules.
- [ ] **Step 2: Run inventory tests to verify failure:** `python -m pytest -q tests/test_migrate_safe_only_releases.py -k inventory`.
- [ ] **Step 3: Implement immutable inventory generation** using asset IDs and exact size/SHA/member identities; unknown or unverifiable objects classify as keep/block, never delete.
- [ ] **Step 4: Write failing repack tests** proving member bytes, sizes, hashes and deterministic ZIP output are exact and non-SAFE members are absent.
- [ ] **Step 5: Implement `repack_mixed_asset`** with safe-name validation, no links/traversal, stored compression and fixed ZIP metadata.
- [ ] **Step 6: Run all migration-tool tests** and expect PASS.
- [ ] **Step 7: Commit:** `git commit -m "feat(dataset): inventory SAFE-only migration"`.

### Task 5: Add catalog cutover, parity gate and guarded resumable deletion

**Files:**
- Modify: `tools/migrate_safe_only_releases.py`
- Modify: `tests/test_migrate_safe_only_releases.py`
- Modify: `tools/restore_alina.py`
- Test: `tests/test_restore_alina.py`

**Interfaces:**
- Produces: `build_safe_catalog(source_catalog, replacements) -> dict[str, Any]` containing only SAFE/replay-compatible rows.
- Produces: `prove_safe_parity(source_rows, destination_rows, remote_assets) -> dict[str, Any]` with `eligible`, exact counts/bytes and failures.
- Produces: CLI destructive gates `--execute --inventory-sha256 <64hex> --batch-size <1..100>`; checkpoint schema `alina.safe_only_migration_checkpoint.v1`.
- Produces: final report status `SAFE_ONLY_MIGRATION_COMPLETE` or `SAFE_ONLY_MIGRATION_INCOMPLETE`.

- [ ] **Step 1: Write failing tests** for exact catalog cutover, remote replacement mismatch, missing SAFE row, extra non-SAFE row, inventory drift, interrupted upload/delete resume, rate limits and idempotent rerun.
- [ ] **Step 2: Run tests to verify failure:** `python -m pytest -q tests/test_migrate_safe_only_releases.py -k 'catalog or parity or execute or resume'`.
- [ ] **Step 3: Implement replacement upload and remote verification**, then generate the SAFE-only catalog without mutating the source file until parity passes.
- [ ] **Step 4: Implement guarded deletion** only for IDs from the frozen inventory whose current remote identity still matches; persist a checkpoint after every bounded operation.
- [ ] **Step 5: Extend restore tests** proving post-migration selection reaches `REPLAY_READY_COMPLETE` for every certified working-set class, diagnostics are ignored even if present beside data assets, and Task 3's recovery-proof interlock is mandatory.
- [ ] **Step 6: Run migration and restore tests** and expect PASS.
- [ ] **Step 7: Commit:** `git commit -m "feat(dataset): guard historical SAFE-only cleanup"`.

### Task 6: Add the explicit GitHub-hosted maintenance workflow

**Files:**
- Replace: `.github/workflows/cleanup-incomplete-v2-releases.yml`
- Modify: `tests/test_workflow_bounds.py`
- Modify: `.github/workflows/recovery-contract.yml`

**Interfaces:**
- Consumes: Task 5 CLI.
- Produces: manual `workflow_dispatch` inputs `mode=dry-run|execute`, `inventory_sha256`, `batch_size`; concurrency `safe-only-dataset-migration`; artifact/report and durable checkpoint commit on `main`.

- [ ] **Step 1: Write failing workflow tests** requiring `workflow_dispatch` only, GitHub-hosted runner, default dry-run, write permission only for execute, exact inventory digest, bounded batch size, no phase mutation, no collector cancellation and no self-hosted/LFS commands.
- [ ] **Step 2: Run tests to verify failure:** `python -m pytest -q tests/test_workflow_bounds.py -k safe_only_migration`.
- [ ] **Step 3: Implement the workflow** with preflight inventory, explicit execute gate, checkpoint upload/commit and final report; never schedule it.
- [ ] **Step 4: Add migration tests to `recovery-contract.yml`** without triggering a destructive run.
- [ ] **Step 5: Run workflow/recovery-contract tests** and expect PASS.
- [ ] **Step 6: Commit:** `git commit -m "ci(dataset): add guarded SAFE-only migration"`.

### Task 7: Validate, publish and run the non-destructive real inventory

**Files:**
- Modify: `README.md`
- Modify: `docs/DISASTER_RECOVERY.md`
- Modify: `docs/GITHUB_HOSTED_DATASET_BACKTESTS.md`
- Generated at runtime: `runtime/recovery/safe-only/SAFE_ONLY_MIGRATION_REPORT.json` (ignored, then published as workflow evidence).

**Interfaces:**
- Consumes: all prior tasks, especially Task 3's clone/update recovery proof.
- Produces: exact dry-run counts/bytes and deletion plan bound to current GitHub inventory.

- [ ] **Step 1: Run syntax and deterministic suites:** `python -m py_compile tools/publish_dataset_v2_release.py tools/recover_dataset_v2_capsules.py tools/migrate_safe_only_releases.py tools/restore_alina.py` and targeted pytest files from Tasks 1–5.
- [ ] **Step 2: Run `git diff --check`, launcher/restore tests and security scans**; require zero failures and no self-hosted/LFS/real-execution regression.
- [ ] **Step 3: Document complete certified-working-set clone/update, diagnostic register, historical dry-run and the distinction between technical viability and profitability.**
- [ ] **Step 4: Publish non-empty commits to `main`, re-read the remote HEAD/tree/files and preserve concurrent collector commits via fast-forward-only integration.**
- [ ] **Step 5: Trigger or execute only the real dry-run inventory**, record exact bytes by disposition and do not delete anything until its report and inventory SHA are reviewed.
- [ ] **Step 6: Execute bounded purge batches only after the dry-run proves SAFE parity and fresh-clone/incremental recovery proof**, resume until the final report is complete, then re-run canonical restoration inventory comparison.

### Task 8: Ordered final follow-up gate — measure viable collector yield

**Files:**
- Create: `tools/build_quality_rejection_metrics.py`
- Create: `tests/test_quality_rejection_metrics.py`

**Interfaces:**
- Consumes: lightweight quality registers produced after Task 2.
- Produces: `QUALITY_REJECTION_METRICS.json` bound to register SHA-256s, grouped by venue/family/cause/bytes/events, with an ordered remediation backlog.

- [ ] **Step 1: Write failing metrics tests** proving exact counts/bytes, digest binding, duplicate-register rejection and deterministic cause ordering.
- [ ] **Step 2: Implement and run the metrics builder**, then publish a real current baseline without changing COLLECT.
- [ ] **Step 3: Write a focused follow-up implementation plan from the measured top causes**; each collector fix must name its exact module, failing test and measurable SAFE-yield acceptance threshold before code changes.
- [ ] **Step 4: Commit:** `git commit -m "feat(dataset): measure collector rejection causes"`.

The measured follow-up plan is the next workstream after this migration. It
must implement collector fixes in descending verified impact, compare
before/after SAFE yield, then feed only the enlarged certified corpus through
replay, backtest, OOS, forward-paper and net-PnL proof. Copy-Vault, Lead-Lag
and Cross-Venue keep independent honest verdicts against +5 USD net/day; no
defective data may be relabeled or interpolated to improve the result.


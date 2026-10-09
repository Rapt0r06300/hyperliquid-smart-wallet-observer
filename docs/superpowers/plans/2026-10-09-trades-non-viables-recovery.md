# Non-Viable Trades Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent stale or non-viable evidence from entering Alina replays while recovering every release asset that can be proven SAFE and replay-compatible.

**Architecture:** Keep the existing single-repository catalog, collectors, replay adapters, and Release restore path. Add source-binding gates around generated metrics, make restore inventory classification fail-closed and physically separate usable evidence from quarantine/diagnostics, and lock the existing native multi-trade splitter into four-venue integration tests.

**Tech Stack:** Python 3.12 standard library, pytest, GitHub Actions, GitHub Releases.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

## Global Constraints

- PAPER / READ-ONLY / FAIL-CLOSED; no real or testnet execution.
- GitHub-hosted runners only; no self-hosted runner or user-PC dependency.
- Keep collection running; do not change phase from COLLECT.
- Reuse the canonical runtime and catalog; do not create a parallel data system.
- Never promote missing, corrupt, unverified, or non-replayable evidence to SAFE.
- Do not import the retired Dataset V2 repository.

## Review Focus

- A metrics file generated from an older index must be rejected before publication.
- Missing or contradictory manifest evidence must route assets to quarantine, never usable restore.
- ZIP and shard-member bytes must be verified independently before usable materialization.
- Interrupted downloads must resume without turning partial bytes into verified assets.
- Multi-trade source frames must produce every native trade exactly once on all four venues.

---

### Task 1: Bind metrics publication to the current catalog

**Files:**
- Modify: `tools/build_catalog_metrics.py`
- Modify: `tests/test_dataset_metrics.py`
- Modify: `.github/workflows/dataset-metrics-v2.yml`

**Interfaces:**
- Produces: `verify_metrics_source(index_path, metrics_path) -> dict[str, Any]`
- Consumes: existing `source_index_sha256` and `TOTAL_SHARDS` metrics fields.

- [x] Add a failing test for stale index SHA and shard-count mismatch.
- [x] Implement the fail-closed verifier.
- [x] Rebuild metrics after every fetch/reset immediately before commit and push.
- [x] Run dataset metrics tests.

### Task 2: Restore only proven usable evidence

**Files:**
- Modify: `tools/restore_alina.py`
- Modify: `tests/test_restore_alina.py`
- Modify: `RESTORE_ALINA.cmd`
- Modify: `RESTORE_ALINA.sh`

**Interfaces:**
- Produces: classified inventory with `usable`, `quarantine`, `diagnostic`, and `excluded` outcomes.
- Produces: resumable verified downloads and a non-success exit when usable restoration is incomplete.

- [x] Add failing tests for SAFE/replay filtering, unknown evidence, ZIP corruption, and interrupted resume.
- [x] Classify from SHA-bound RUN_MANIFEST rows without inventing evidence.
- [x] Download into separate roots and materialize only verified usable assets.
- [x] Report present, downloaded, verified, missing, quarantined, and excluded assets.
- [x] Run restore tests.

### Task 3: Prove four-venue multi-trade wiring

**Files:**
- Add: `tests/test_native_trade_batch_split.py`
- Modify only if a test fails: `src/hl_observer/collection/native_market_tape.py` or `native_venue_coordinator.py`

**Interfaces:**
- Consumes: `native_tick_envelopes(venue, payload) -> list[TickEnvelope]`.
- Proves: per-row native identity, shared batch digest, stable batch index, no truncation.

- [x] Add deterministic cases for Bybit, OKX, Gate, and Bitget.
- [x] Verify every source row becomes one replay event.
- [x] Run collector/replay tests.

### Task 4: Final gates and publication

**Files:**
- Modify: canonical spec acceptance notes only if behavior changes require it.

**Interfaces:**
- Consumes: Tasks 1–3 verification evidence.

- [x] Run targeted tests, compilation, workflow policy scans, and the available project suite.
- [x] Inspect the real diff and confirm no execution/self-hosted path was enabled.
- [ ] Create one non-empty commit against the latest real `main`.
- [ ] Update `main`, verify the remote HEAD/tree, and inspect triggered workflow results.
- [ ] Re-read catalog metrics/quarantine counters and report only measured gains.

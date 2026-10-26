# Copy-Vault Fill History and Continuity Implementation Plan

> **For agentic workers:** Implement this plan task-by-task in the current Alina repository; preserve existing local work and use the canonical control plane.

**Goal:** Collect up to the public API's available recent fill history for selected Copy-Vault leaders, retain gap-reconciled forward fills across campaign handoffs, and make collection/import gaps explicit.

**Architecture:** Reuse the existing resumable Copy-Vault campaign cursor, frozen selection, cloud collector, SAFE publisher, and local restore engine. Store research history as snapshot evidence, forward fills as separate reconciled evidence, and advance per-wallet checkpoints only after durable publication. Do not add a parallel database or change the active economic family.

**Tech Stack:** Python, Hyperliquid public `info`/WebSocket APIs, existing GitHub Actions campaign control plane, existing SAFE release/catalog and AlinaSync restore.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md` (Copy-Vault collection contract and scheduler redesign).

## Global Constraints

- PAPER / READ-ONLY / FAIL-CLOSED; only public `/info` and WebSocket observation.
- Copy-Vault is the only executable economic family.
- Keep historical snapshot fills separate from forward proof; missing history stays partial/unavailable.
- Respect the Hyperliquid API limits: 2,000 fills per response, 10,000 latest fills per address, 10 unique user subscriptions per IP.
- Reuse campaign cursor/checkpoint/publication receipts; no Supabase or second ledger.
- Never change local Git refs destructively or overwrite existing AlinaSync data.

## Review Focus

- REST backfill is bounded, paginated by adaptive windows, deduplicated, and explicitly reports the 10,000-fill visibility ceiling.
- Reconnect and next-campaign gaps are reconciled from the last durably published per-wallet cursor.
- Historical snapshots cannot be counted as forward fills or PnL proof.
- Zero fills, rejected campaigns, skipped work, and stale local imports are reported as distinct states.
- Invalid/old campaign manifests cannot starve current Copy-Vault collection silently.

### Task 1: Backfill/history evidence and per-wallet checkpoints

**Files:** `tools/collect_cloud_copy_vault.py`, `tools/run_resumable_campaign.py`, campaign cursor helpers, `tests/test_collect_cloud_copy_vault.py`.

Add a bounded recent-history pass for newly selected leaders, save it as `copy_vault_snapshot` with REST provenance, preserve exact counts and incomplete reasons, and return a per-wallet checkpoint in the collection result. Keep the existing forward family and reconciliation rules unchanged.

### Task 2: Durable cross-campaign handoff and controller recovery

**Files:** `.github/workflows/create-resumable-campaigns.yml`, `.github/workflows/resumable-campaign-controller.yml`, `.github/workflows/resumable-campaign-worker.yml`, relevant workflow/campaign tests.

Carry the latest published wallet checkpoints into the next Copy-Vault campaign. Reconcile from each checkpoint before advancing it. Make the controller dispatch campaign creation when collection is active but no valid Copy-Vault work is queued, while rejecting malformed current-epoch state visibly.

### Task 3: Honest coverage and local import diagnostics

**Files:** Copy-Vault coverage receipt/report generation, `tools/sync_complete_clone.py` or existing restore reporting only if a safe minimal correction is needed, corresponding tests.

Report fills separately from L2/position/snapshot shards. Surface current local catalog SHA, restore report time, downloaded/reused counts, and releases absent from local sync. Preserve the clean-`main` and local-change safety gates.

### Task 4: Verification

Run focused unit and workflow contract tests, validate syntax and report counters, inspect the final diff and Git state, and state any remaining external GitHub queue/import blocker exactly.

# Copy-Vault Continuous Lab Implementation Plan

**Goal:** Turn `LANCER_LAB_QUANT_COPY_VAULT.cmd` into a resumable, continuously running local Copy-Vault replay/backtest laboratory with a live French dashboard.

**Architecture:** Reuse the existing AlinaSync SAFE restore, `copy_vault_safe_bridge`, canonical V21 replay evaluator, and immutable improvement registry. Add an effectively unbounded deterministic low-discrepancy candidate stream, append-only trial receipts and atomic checkpoints bound to the SAFE selection digest, then refresh one HTML report while the process runs. Ctrl+C must stop only after persisting the current completed trial and final dashboard.

**Tech Stack:** Windows CMD, Python standard library, existing Copy-Vault V21 replay engine and AlinaSync SAFE SQLite/catalog receipts.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md` (updated in place only if a normative contract change is required).

## Global Constraints

- PAPER / READ-ONLY / FAIL-CLOSED; no order, key, signature, deposit, withdrawal, or transaction.
- Copy-Vault is the only executable economic family.
- Only catalog-bound, hash-verified SAFE inputs with exact identity/counts can enter the replay.
- TRAIN selects candidates; VALIDATION/OOS/FORWARD are not reused for tuning.
- Every tried configuration counts toward multiple-testing pressure; no synthetic observations or missing-as-zero conversions.
- Preserve all existing user changes and append-only candidate history.
- The double-click default targets `C:\Users\flo\Desktop\Projet invest\LANCER_LAB_QUANT_COPY_VAULT.cmd` and runs until Ctrl+C.

## Review Focus

- Repeated launches resume the same data-bound sequence without replaying a completed candidate.
- SAFE corpus fingerprint changes start a separate evidence-bound sequence without deleting prior receipts.
- Ctrl+C during evaluation retains all completed trial receipts and a final readable report.
- Browser `file://` display reflects progress without relying on cross-origin fetch.
- Large cumulative trial counts remain explicit and cannot turn exploratory TRAIN into proof.

### Task 1: Deterministic streaming candidate source and durable receipts

**Files:** Modify `src/hl_observer/backtesting/copy_vault_local_lab.py`.

Produce candidates from a deterministic bounded-domain low-discrepancy sequence indexed by a persistent integer. Bind checkpoints and append-only trial rows to the exact SAFE selection digest. Persist each completed trial and freeze each strict TRAIN improvement before continuing.

### Task 2: Continuous controller and live HTML

**Files:** Modify `tools/alina_quant_lab_console.py` and `LANCER_LAB_QUANT_COPY_VAULT.cmd`.

Run bounded replay batches repeatedly against the verified local SAFE workspace; regenerate the live report periodically and on every champion change; catch Ctrl+C and finalize receipts. Default CMD mode becomes continuous SAFE research.

### Task 3: Verify wiring and final state

Inspect the resulting diffs, run syntax/format integrity checks that do not invoke economic or software test suites, validate the candidate sequence and checkpoint artifacts with small deterministic local invocations where possible, and report exact behavior and limits.

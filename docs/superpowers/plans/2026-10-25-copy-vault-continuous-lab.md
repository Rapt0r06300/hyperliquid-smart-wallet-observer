# Copy-Vault Continuous Lab Implementation Plan

**Goal:** Turn `LANCER_LAB_QUANT_COPY_VAULT.cmd` into a resumable, continuously running local Copy-Vault replay/backtest laboratory with a live French dashboard.

**Architecture:** Read the active canonical `DATA_INDEX.json` and SAFE manifests locally; do not invoke a restore/download bridge. Verify catalog identity, SAFE manifest binding, local shard size/SHA-256 (reusing a prior hash only when the immutable file identity is unchanged), then materialize every available replay-compatible Copy-Vault SAFE shard. Keep missing shards explicit and exploratory results unproven. Reuse the canonical V21 replay evaluator and immutable improvement registry. Search the bounded 11-parameter domain with a deterministic low-discrepancy stream (about 6.07 trillion valid configurations), append-only per-selection trial receipts, a global multiplicity count, and atomic checkpoints bound to the SAFE selection digest. Refresh one French HTML report while work runs. Ctrl+C must checkpoint completed trials and finalize the dashboard.

**Tech Stack:** Windows CMD, Python standard library, existing Copy-Vault V21 replay engine and AlinaSync SAFE SQLite/catalog receipts.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md` (updated in place only if a normative contract change is required).

## Global Constraints

- PAPER / READ-ONLY / FAIL-CLOSED; no order, key, signature, deposit, withdrawal, or transaction.
- Copy-Vault is the only executable economic family.
- Only active-catalog-bound, manifest-bound, replay-compatible SAFE inputs with exact local identity/hash can enter the replay; PARTIAL and missing rows remain visible and cannot support a proof.
- TRAIN selects candidates; VALIDATION/OOS/FORWARD are not reused for tuning.
- Every tried configuration counts toward multiple-testing pressure; no synthetic observations or missing-as-zero conversions.
- Preserve all existing user changes and append-only candidate history.
- The double-click default targets `C:\Users\flo\Desktop\Projet invest\LANCER_LAB_QUANT_COPY_VAULT.cmd` and runs until Ctrl+C.

## Review Focus

- Repeated launches resume the same data-bound sequence without replaying a completed candidate; prior campaigns count toward multiple-testing correction.
- SAFE corpus fingerprint changes start a separate evidence-bound sequence without deleting prior receipts.
- Ctrl+C during evaluation retains all completed trial receipts and a final readable report.
- Browser `file://` display reflects progress without relying on cross-origin fetch.
- Large cumulative trial counts remain explicit and cannot turn exploratory TRAIN into proof.

### Task 1: Deterministic streaming candidate source and durable receipts

**Files:** Modify `src/hl_observer/backtesting/copy_vault_local_lab.py`.

Produce candidates from a deterministic bounded-domain low-discrepancy sequence indexed by a persistent integer. Bind checkpoints and append-only trial rows to the exact SAFE selection digest. Persist each completed trial and freeze each strict TRAIN improvement before continuing.

### Task 2: Continuous controller and live HTML

**Files:** Modify `tools/alina_quant_lab_console.py` and `LANCER_LAB_QUANT_COPY_VAULT.cmd`.

Run the Copy-Vault campaign continuously against the verified local SAFE workspace; regenerate the live report periodically and on every improvement; catch Ctrl+C and finalize receipts. Default CMD mode becomes continuous SAFE research, and `--once` remains an explicit bounded option.

### Task 3: Verify wiring and final state

Inspect the resulting diffs and run syntax/format integrity checks that do not invoke economic or software test suites. Report exact behavior and limits; do not launch a research campaign as part of implementation.

**Implementation status:** Tasks 1–3 are complete. Python syntax compilation and `git diff --check` passed. No software test suite or economic campaign was run in this implementation turn.

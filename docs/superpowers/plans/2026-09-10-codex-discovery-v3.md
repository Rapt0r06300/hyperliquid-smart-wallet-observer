# Codex Discovery V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. This project explicitly forbids subagents for the active Codex Goal, so execution is inline and sequential.

**Goal:** Implement a discovery-first quantitative research controller surface that records every hypothesis, measures structural novelty locally, forces rediscovery after stagnant parameter-only iterations, and keeps bulk evaluation on the existing local CPU runners.

**Architecture:** Add one pure-stdlib research ledger module plus one local CLI. Reuse the existing experiment and batch runners; enrich compact batch summaries with hypothesis linkage instead of creating a second backtester. Update the repo-local Codex skill/runbook so the model alternates between Discovery, Tournament, Exploit and Rediscovery while final economic proof remains outside the adaptive search surface.

**Tech Stack:** Python stdlib, pytest, existing `hl_observer.research.experiment_protocol`, existing `tools/codex_quant_experiment.py` and `tools/codex_quant_batch.py`.

**Spec:** `docs/superpowers/specs/2026-09-10-codex-discovery-v3-design.md`

## Global Constraints

- PAPER/read-only only; no order execution, signing, keys, deposits or withdrawals.
- Final target stays >= +4.00 USD NET/day separately for `copy_vault`, `lead_lag`, `cross_venue_dislocation_v2`.
- Agent LLM remains single-controller; local non-LLM CPU parallelism is unrestricted.
- Final held-out/OOS/forward evidence is not used to steer discovery after it is observed.
- Existing 775 sealed controls and economic gates are not weakened.
- Runtime ledger is append-only JSONL and is not itself economic proof.

---

### Task 1: Hypothesis ledger core

**Files:**
- Create: `src/hl_observer/research/hypothesis_ledger.py`
- Create: `tests/test_hypothesis_ledger.py`

**Interfaces:**
- `validate_record(payload) -> dict`
- `semantic_fingerprint(record) -> str`
- `novelty_score(candidate, history) -> float`
- `append_record(path, payload) -> dict`
- `load_records(path, family=None) -> list[dict]`
- `rediscovery_required(history, hypothesis_id) -> bool`
- `compact_status(history, family=None) -> dict`

- [ ] Write failing unit tests for schema validation, append-only behavior, stable fingerprints, set-order invariance, duplicate novelty=0, parameter-only classification effects, family filtering and the two-step anti-loop rule.
- [ ] Run `pytest tests/test_hypothesis_ledger.py -q` and confirm RED.
- [ ] Implement the pure local module with no network imports and atomic append semantics.
- [ ] Re-run the same test file and confirm GREEN.

### Task 2: Local ledger CLI

**Files:**
- Create: `tools/codex_hypothesis_ledger.py`
- Create: `tests/test_codex_hypothesis_ledger_cli.py`

**Interfaces:**
- `register <json>` validates and appends.
- `score <json>` reports fingerprint, novelty and duplicate state without writing.
- `status [--family FAMILY]` emits compact JSON.
- `needs-rediscovery <hypothesis_id>` emits a machine boolean/verdict.

- [ ] Write failing CLI tests using a temporary runtime directory.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement argparse commands with default `runtime/codex_research/HYPOTHESIS_LEDGER.jsonl` and deterministic JSON output.
- [ ] Re-run targeted tests and confirm GREEN.

### Task 3: Enrich local batch summaries

**Files:**
- Modify: `tools/codex_quant_batch.py`
- Modify: `tests/test_codex_quant_batch.py`

**Interfaces:**
- Every compact batch result carries `family`, `hypothesis_id`, `phase`, and compact `trials` when present.
- Existing fields and zero-model-roundtrip contract remain backward compatible.

- [ ] Add failing assertions to existing batch tests.
- [ ] Run targeted batch tests and confirm RED.
- [ ] Extend `_compact_result` only; do not duplicate evaluator/backtest logic.
- [ ] Re-run batch tests and confirm GREEN.

### Task 4: Encode Discovery/Tournament/Exploit/Rediscovery in Codex instructions

**Files:**
- Modify: `.agents/skills/alina-quant-research/SKILL.md`
- Modify: `docs/CODEX_GOAL_RUNBOOK.md`
- Modify: `AGENTS.md`
- Create: `tests/test_codex_discovery_v3_contract.py`

**Interfaces:**
- Discovery requires >=8 structurally distinct hypotheses before a new large CPU campaign.
- Historical ten mechanisms are baselines, not novelty.
- Tournament scores novelty, causal plausibility, data availability, executable headroom, information gain and falsification cost.
- Two consecutive parameter-only iterations without comparable economic progress force Rediscovery.
- External research is allowed proactively once per Discovery cycle, then the loop returns to local compute.
- Prediction metrics never replace executable net economics.

- [ ] Write doc-contract tests first and confirm RED.
- [ ] Update skill/runbook; keep `AGENTS.md` to a short pointer only.
- [ ] Re-run doc-contract tests and confirm GREEN.

### Task 5: Verification and finish

**Files:** all files above only unless a failing existing contract requires a minimal compatible adjustment.

- [ ] Run targeted suite: `pytest -q tests/test_hypothesis_ledger.py tests/test_codex_hypothesis_ledger_cli.py tests/test_codex_quant_batch.py tests/test_codex_discovery_v3_contract.py`.
- [ ] Run `python -m compileall -q src/hl_observer/research/hypothesis_ledger.py tools/codex_hypothesis_ledger.py tools/codex_quant_batch.py`.
- [ ] Run the relevant existing Codex quant protocol tests.
- [ ] Inspect exact HEAD and GitHub CI; never claim global green until the exact-SHA statuses are actually green.
- [ ] Produce the final <=4000-character Goal text that points at `$alina-quant-research` rather than duplicating the full workflow.

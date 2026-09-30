# Codex Discovery V3.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a compact local research control plane that reduces Codex context/quota waste while improving memory-driven, semantically diverse alpha discovery.

**Architecture:** Keep Discovery V3.1 as the economic/scientific controller, then add three offline helpers around it: structured process memory, a compact resume/context pack, and a deterministic semantic candidate generator. `AGENTS.md` becomes a router; detailed discovery mechanics stay lazy-loaded in the skill/runbook. No new trading family or execution path is introduced.

**Tech Stack:** Python 3.11 standard library, existing `hl_observer.research.hypothesis_ledger`, pytest, GitHub CI.

**Spec:** `docs/superpowers/specs/2026-09-10-codex-discovery-v32-design.md`

## Global Constraints

- `SECURITY.md` and `docs/HYPERSMART_CONSTITUTION.md` retain higher authority.
- Paper/read-only only; no mainnet/testnet order submission, signing, key handling, deposits or withdrawals.
- Three canonical economic families remain `copy_vault`, `lead_lag`, `cross_venue_dislocation_v2`.
- Final target remains >= +4.00 USD NET/day per family, separately, under exact-HEAD machine gates.
- No new heavyweight ML dependency for V3.2.
- Runtime research ledgers remain append-only.
- No LLM subagents inside economic Discovery campaigns.

---

### Task 1: Process memory core

**Files:**
- Create: `src/hl_observer/research/process_memory.py`
- Test: `tests/test_codex_process_memory.py`

**Interfaces:**
- Produces `validate_process_record(payload) -> dict`
- Produces `append_process_record(path, payload) -> dict`
- Produces `load_process_records(path, family=None) -> list[dict]`
- Produces `process_memory_summary(records, family=None) -> dict`
- Produces `candidate_memory_effect(candidate, records) -> dict`

- [ ] Write tests for schema validation, append-only behavior, high-confidence repeated-failure veto, positive-memory bounded boost and retest-condition override.
- [ ] Run the new test module and verify it fails because `process_memory` does not exist.
- [ ] Implement the minimal pure/offline process-memory module.
- [ ] Run the focused tests until green.

### Task 2: Versioned historical seed memory

**Files:**
- Create: `docs/quant/HISTORICAL_EXPERIMENT_MEMORY.jsonl`
- Test: `tests/test_codex_historical_memory.py`

**Interfaces:**
- Seed records use the same V3.2 process-memory schema.
- Historical records are guidance/provenance, never economic certification.

- [ ] Write tests that every JSONL line validates, all three families are represented, and records explicitly identify historical/non-certifying provenance.
- [ ] Verify tests fail while the seed file is absent.
- [ ] Add a compact seed set containing high-confidence lessons: Cross-Venue taker/taker cost/headroom failure, Lead-Lag coverage/causality pitfalls, Copy-Vault stale/scoring/promotion proof pitfalls, contamination/non-canonical PnL, and general anti-retuning/search-leakage lessons.
- [ ] Run focused tests until green.

### Task 3: Compact one-command research context

**Files:**
- Create: `src/hl_observer/research/research_context.py`
- Create: `tools/codex_research_context.py`
- Test: `tests/test_codex_research_context.py`

**Interfaces:**
- Produces `build_research_context(repo_root, family=None, ledger_path=None, process_memory_path=None) -> dict`
- CLI supports `--auto`, `--family`, `--ledger`, `--process-memory`, `--out`.
- Default stdout is compact JSON and performs no network I/O.

- [ ] Write tests using a temporary repo fixture: auto-family selection, compact ledger/process-memory summaries, HEAD fallback, next-action derivation and output-size discipline.
- [ ] Verify expected RED state.
- [ ] Implement minimal context builder and CLI.
- [ ] Run focused tests until green.

### Task 4: Semantic discovery engine

**Files:**
- Create: `src/hl_observer/research/semantic_discovery.py`
- Create: `tools/codex_semantic_discovery.py`
- Create: `.agents/skills/alina-quant-research/references/semantic-catalog-v32.json`
- Test: `tests/test_codex_semantic_discovery.py`

**Interfaces:**
- `load_catalog(path) -> dict`
- `generate_semantic_plans(catalog, family, limit, seed) -> list[dict]`
- `rank_semantic_plans(plans, ledger_records, process_records, shortlist) -> list[dict]`
- CLI supports `--family`, `--pool-size`, `--shortlist`, `--seed`, `--catalog`, `--ledger`, `--process-memory`, `--out`.

- [ ] Write tests for deterministic generation, structural validity, exact dedupe, failure veto, retest override, archetype diversity and shortlist determinism.
- [ ] Verify RED state.
- [ ] Implement deterministic local generation and explainable empirical priority scoring using only existing dependencies/std-lib.
- [ ] Run focused tests until green.

### Task 5: Route Codex through V3.2 efficiently

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/CODEX_GOAL_RUNBOOK.md`
- Modify: `.agents/skills/alina-quant-research/SKILL.md`
- Modify: `.agents/skills/alina-quant-research/references/discovery-v31.md` or supersede with a V3.2 reference while retaining compatibility.
- Test: `tests/test_codex_discovery_v3_contract.py`

**Interfaces:**
- Startup/resume command becomes `python tools/codex_research_context.py --auto`.
- Discovery may request a large local semantic pool and read only the shortlist.
- Full historical Git/775 scans are forbidden as a normal resume mechanism.

- [ ] Update contract tests first to require V3.2 markers, compact AGENTS, context command, process memory and semantic discovery references.
- [ ] Verify tests fail on current V3.1 docs.
- [ ] Rewrite `AGENTS.md` as a compact router and update lazy-loaded runbook/skill/reference.
- [ ] Run focused contract tests until green.

### Task 6: Verification and regression gate

**Files:**
- Test: all new focused tests plus existing ledger/Discovery/document-authority tests.

- [ ] Run `pytest -q tests/test_codex_process_memory.py tests/test_codex_historical_memory.py tests/test_codex_research_context.py tests/test_codex_semantic_discovery.py tests/test_hypothesis_ledger.py tests/test_codex_hypothesis_ledger_cli.py tests/test_codex_discovery_v3_contract.py tests/test_document_authority.py`.
- [ ] Run Ruff on new/modified Python files.
- [ ] Verify document-authority gate remains PASS.
- [ ] Commit only after focused verification is green; then inspect exact-HEAD CI/status without claiming economic success.

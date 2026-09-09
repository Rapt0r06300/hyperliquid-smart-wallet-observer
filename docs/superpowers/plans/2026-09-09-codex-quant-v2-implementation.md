# Codex Quant Research V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use Superpowers `executing-plans` inline. **No subagents for this project Goal.**

**Goal:** Build a repo-local Codex quant-research skill and a local experiment protocol that turns a compact `EXPERIMENT_SPEC.json` into many bounded local trials plus one compact `RESULT_SUMMARY.json`, without touching scheduled automations.

**Architecture:** Codex remains the research director; Python and the existing Alina research engines do repetitive computation locally. `experiment_protocol.py` validates and fingerprints experiment specs, handles cache/state, and normalizes compact summaries. `tools/codex_quant_experiment.py` resolves a project evaluator, reuses `tools/outils_recherche.py`, persists detailed local artifacts under `runtime/`, and prints only the compact summary. The repo-local skill tells Codex when and how to use this loop.

**Tech Stack:** Python 3.11+, stdlib (`dataclasses`, `hashlib`, `importlib`, `json`, `pathlib`, `subprocess`), pytest, existing `tools/outils_recherche.py` / Optuna stack when installed.

**Spec:** `docs/superpowers/specs/2026-09-09-codex-quant-v2-design.md`

## Global Constraints

- Paper/read-only only; add no order, signing, key, wallet, deposit or withdrawal capability.
- One AI agent; no spawn/fan-out/subagent behavior.
- Do **not** modify ChatGPT scheduled automations in this implementation.
- Reuse existing optimizers and anti-overfit validators instead of duplicating them.
- Missing scientific inputs fail closed; missing values never become zero silently.
- OOS/forward evidence may not be reclassified as fresh after retuning.
- Runtime trial databases/logs/results stay local and ignored by Git.
- `main` is the only persistent delivered branch.

---

### Task 1: Experiment protocol contracts

**Files:**
- Create: `src/hl_observer/research/experiment_protocol.py`
- Test: `tests/test_codex_quant_experiment.py`

**Interfaces:**
- `ExperimentSpec.from_mapping(payload: Mapping[str, Any]) -> ExperimentSpec`
- `ExperimentSpec.signature() -> str`
- `load_spec(path: Path) -> ExperimentSpec`
- `result_dir(runtime_root: Path, experiment_id: str) -> Path`
- `load_cached_summary(runtime_root: Path, signature: str) -> dict[str, Any] | None`
- `write_summary_atomic(path: Path, payload: Mapping[str, Any]) -> None`
- `write_goal_state_atomic(path: Path, payload: Mapping[str, Any]) -> None`

- [ ] **Step 1: Write failing tests** for valid specs, missing required scientific fields, invalid family/engine/phase, deterministic signatures, signature changes when SHA/data/cost/split/seed change, safe experiment IDs, atomic JSON writes and cache lookup.
- [ ] **Step 2: Run targeted pytest and verify RED.**
- [ ] **Step 3: Implement minimal immutable dataclasses/validation/canonical JSON hashing.** Evaluator must match `hl_observer.*:<callable>` or `tools.*:<callable>`; output paths must remain under the supplied runtime root.
- [ ] **Step 4: Run targeted pytest and verify GREEN.**
- [ ] **Step 5: Refactor while preserving the public interfaces and rerun tests.**

### Task 2: Local experiment runner and compact summary

**Files:**
- Create: `tools/codex_quant_experiment.py`
- Extend: `tests/test_codex_quant_experiment.py`

**Interfaces:**
- `resolve_evaluator(spec: ExperimentSpec) -> Callable[..., Mapping[str, Any]]`
- `run_experiment(spec: ExperimentSpec, *, runtime_root: Path, force: bool = False, force_reason: str | None = None, optimizer: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]`
- CLI: `python tools/codex_quant_experiment.py SPEC.json [--runtime-root runtime/codex_experiments] [--force --reason TEXT]`

- [ ] **Step 1: Write failing integration tests** with a deterministic in-test evaluator and injected optimizer; assert multiple trials are delegated, seed/budget/search-space are propagated, compact summary fields are stable, trial failures stay counted, and an identical complete signature returns cache instead of rerunning.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement evaluator resolution with an allowlisted project namespace and integrate the existing `tools.outils_recherche.optimiser`.** No duplicate Optuna implementation.
- [ ] **Step 4: Persist `SPEC.json`, detailed optimizer result, `RESULT_SUMMARY.json`, signature index and compact goal state atomically.**
- [ ] **Step 5: Enforce `--force` only with a non-empty recorded reason; forced rerun receives a distinct run record but does not claim fresh OOS/forward evidence automatically.**
- [ ] **Step 6: Run targeted tests and verify GREEN.**

### Task 3: Repo-local Codex skill

**Files:**
- Create: `.agents/skills/alina-quant-research/SKILL.md`
- Create: `.agents/skills/alina-quant-research/references/experiment-spec.md`

**Interfaces:**
- Skill trigger: Alina edge research, backtests, parameter search, quantitative validation/certification.
- Skill normal path: inspect compact state -> choose one hypothesis -> write spec -> run local CLI -> read summary first -> inspect detailed artifacts only for a concrete anomaly -> decide REJECT/ITERATE/FREEZE_CANDIDATE/BLOCKED.

- [ ] **Step 1: Write the skill under 500 words with a trigger-only frontmatter description and progressive disclosure.**
- [ ] **Step 2: Put JSON field details/examples in the reference file, not the always-loaded skill.**
- [ ] **Step 3: Explicitly route to existing TPE/QMC/CMA-ES/NSGA-II/Successive-Halving/Hyperband and anti-overfit validators; external tools are used only for a precise information gap.**
- [ ] **Step 4: Verify no instruction asks for subagents or repetitive broad web research.**

### Task 4: Integration guidance and Git hygiene

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/CODEX_GOAL_RUNBOOK.md`
- Modify: `.gitignore`
- Modify: `docs/superpowers/specs/2026-09-09-codex-quant-v2-design.md`

- [ ] **Step 1: Add the new skill/CLI as the preferred research loop while keeping the root instructions compact.**
- [ ] **Step 2: Mark scheduled-automation changes and writer-lease enforcement as deferred/out of scope after user clarification.**
- [ ] **Step 3: Ignore `/runtime/codex_experiments/` and `/runtime/codex_goal_state.json` while preserving source/tests.**
- [ ] **Step 4: Run tests plus Ruff for the new Python files if available.**

### Task 5: Final verification

- [ ] **Step 1:** `pytest -q tests/test_codex_quant_experiment.py` must pass.
- [ ] **Step 2:** Run nearby research/anti-overfit tests affected by imports/interfaces.
- [ ] **Step 3:** `python -m py_compile src/hl_observer/research/experiment_protocol.py tools/codex_quant_experiment.py` must pass.
- [ ] **Step 4:** Run Ruff on changed Python files when available.
- [ ] **Step 5:** Inspect exact final GitHub files/SHA and report limitations honestly; do not claim economic certification from infrastructure tests.

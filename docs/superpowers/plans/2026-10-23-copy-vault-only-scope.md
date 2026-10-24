# CopyVault-Only Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CopyVault the only family executable by AlinaSmartFlow simulations, laboratory runs, replays, backtests, OOS, PnL proof, and scoreboards while preserving every paused family for a reversible future reactivation.

**Architecture:** Reuse `hl_observer.strategies.active_scope` as the single fail-closed authority and derive every canonical analysis/simulation family list from it. Mixed orchestration surfaces must either run CopyVault-only stages or emit an explicit `DISABLED_BY_SCOPE` result; collectors, SAFE restoration, stored evidence, and family implementation modules remain untouched.

**Tech Stack:** Python 3.14, pytest, Windows command launchers, existing AlinaSmartFlow control plane.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

## Global Constraints

- PAPER / READ-ONLY / FAIL-CLOSED; no mainnet or testnet execution.
- `copy_vault` is the only active economic, simulation, replay, backtest, OOS, proof, and scoreboard family.
- Lead-Lag, Cross-Venue, arbitrage, carry/funding, shadow, research-only, unknown, and aliased non-CopyVault families cannot execute through canonical AlinaSmartFlow analysis or simulation entrypoints.
- No environment variable may broaden the scope.
- Do not stop or modify collectors or the active SAFE restoration process.
- Do not delete family code, historical data, or evidence; the pause must remain reversible through a reviewed code change.
- Keep one orchestrator, replay engine, PnL engine, ledger, and scoreboard.

## Review Focus

- A versioned Cross-Venue alias must remain blocked everywhere, including direct simulation APIs.
- A mixed stage with no reliable family attribution must fail closed instead of being treated as CopyVault.
- Family-neutral integrity/quality stages may run but must never produce non-CopyVault PnL or certification.
- Existing stored Lead-Lag/Cross-Venue reports must not appear as current active scoreboard proof.
- Environment variables and direct Python calls must not reactivate a paused family.

---

### Task 1: Central CopyVault-only authority and simulation gate

**Files:**
- Modify: `src/hl_observer/strategies/active_scope.py`
- Modify: `src/hl_observer/runtime/fusion_strategy_runtime.py`
- Modify: `src/hl_observer/strategies/fusion_runtime.py`
- Modify: `src/hl_observer/ui/fusion_status_provider.py`
- Modify: `src/hl_observer/ui/status_routes.py`
- Modify: `src/hl_observer/simulation/economic_objective.py`
- Modify: `src/hl_observer/simulation/economic_campaigns.py`
- Modify: `src/hl_observer/simulation/economic_collection_plan.py`
- Test: `tests/test_active_strategy_scope_v2.py`
- Test: `tests/test_fusion_strategy_runtime.py`
- Test: `tests/test_refactor_fusion_dashboard_e2e.py`
- Test: `tests/test_ui_simulation_status_fast.py`
- Test: `tests/test_economic_objective.py`
- Test: `tests/test_economic_campaigns.py`
- Test: `tests/test_economic_collection_plan.py`

**Interfaces:**
- Consumes: canonical family aliases already defined by `canonical_strategy_family()`.
- Produces: `active_strategy_families() == frozenset({"copy_vault"})`, one reusable fail-closed family assertion for canonical simulations, and UI payloads that expose CopyVault as the sole running bot engine.

- [ ] **Step 1: Write failing tests for the exact one-family scope, alias rejection, environment override rejection, direct simulation rejection, and UI/main-engine CopyVault exclusivity.**
- [ ] **Step 2: Run the targeted tests and confirm failures show the current three-family behavior.**
- [ ] **Step 3: Mark every non-CopyVault family paused and wire simulation/campaign builders to the central authority.**
- [ ] **Step 4: Run the targeted tests and confirm CopyVault still executes while all other families return or raise `DISABLED_BY_SCOPE`.**
- [ ] **Step 5: Commit the central authority and simulation gate.**

### Task 2: CopyVault-only laboratory, replay, and backtest plans

**Files:**
- Modify: `src/hl_observer/ops/lab_alpha.py`
- Modify: `src/hl_observer/ops/historical_analysis_suite.py`
- Modify: `ANALYSER_BACKTESTS_REPLAYS.cmd`
- Test: `tests/test_lab_alpha_e2e.py`
- Test: `tests/test_historical_analysis_launcher.py`
- Test: `tests/test_cmd_historical_analysis_suite.py`

**Interfaces:**
- Consumes: the central active-family authority from Task 1.
- Produces: a deterministic CopyVault-only stage plan and reports carrying `COPY_VAULT_ONLY` plus explicit paused-family metadata.

- [ ] **Step 1: Write failing tests proving the official lab and historical plan contain no Lead-Lag, Cross-Venue, arbitrage, carry/funding, or unattributed economic stage.**
- [ ] **Step 2: Run the targeted tests and confirm the current mixed plan fails them.**
- [ ] **Step 3: Remove non-CopyVault execution from `lab_alpha`, classify historical stages, retain only neutral integrity plus CopyVault stages, and update the launcher banner.**
- [ ] **Step 4: Run the lab/launcher tests and confirm CopyVault behavior and fail-closed scope metadata.**
- [ ] **Step 5: Commit the CopyVault-only lab plan.**

### Task 3: Proof, scoreboard, and certification isolation

**Files:**
- Modify: `src/hl_observer/control_plane/module_pnl_proof.py`
- Modify: `src/hl_observer/simulation/economic_family_scoreboard.py`
- Modify: `src/hl_observer/ops/final_economic_certification.py`
- Modify: `src/hl_observer/ops/paper_canonique.py`
- Test: `tests/test_module_pnl_proof_campaign.py`
- Test: `tests/test_economic_family_scoreboard.py`
- Test: `tests/test_final_economic_certification.py`
- Test: `tests/test_paper_canonique.py`

**Interfaces:**
- Consumes: active families from Task 1 and CopyVault-only artifacts from Task 2.
- Produces: proof and scoreboard outputs containing CopyVault only; direct paused-family certification fails closed.

- [ ] **Step 1: Write failing tests for proof, certification, and scoreboard exclusion of every paused family, including stale stored reports.**
- [ ] **Step 2: Run the targeted tests and confirm current hard-coded three-family lists fail.**
- [ ] **Step 3: Derive canonical proof/scoreboard families from active scope and reject paused-family requests.**
- [ ] **Step 4: Run targeted tests and confirm no historical non-CopyVault evidence is promoted.**
- [ ] **Step 5: Commit proof and scoreboard isolation.**

### Task 4: Canonical documentation and complete verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`
- Modify: `docs/HYPERSMART_CONSTITUTION.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Test: affected scope, simulation, lab, proof, security, and document-authority suites.

**Interfaces:**
- Consumes: implemented behavior from Tasks 1-3.
- Produces: one documented temporary CopyVault-only contract matching machine behavior.

- [ ] **Step 1: Update the existing canonical spec in place and align compact authority documents without creating a parallel spec.**
- [ ] **Step 2: Run targeted suites, then the broad relevant test set, `py_compile`, and `git diff --check`.**
- [ ] **Step 3: Inspect the final diff and HEAD, verify the SAFE restore PID was never controlled, and record any unrelated pre-existing failures exactly.**
- [ ] **Step 4: Commit and push `main`, then fast-forward the desktop checkout only if doing so cannot affect the already loaded restoration process; explicitly state that a running Python process does not load new code.**

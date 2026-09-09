---
name: alina-quant-research
description: Use when researching Alina SmartFlow edge, designing or running backtests, tuning strategy parameters, or validating/certifying copy_vault, lead_lag, or cross_venue_dislocation_v2.
---

# Alina Quant Research

## Core rule

Use model reasoning to choose **which experiment is worth running**; use the local PC for every calculation the PC can do. One LLM agent only: never spawn/fan-out. Local CPU processes/threads/batches are not subagents and are encouraged.

The final target is **>= +4.00 USD NET per observed forward day for each canonical family**, separately. The final gate is `python tools/run_daily_economic_certification.py .`.

## Workflow

1. Read only the minimum authority needed: `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/CODEX_GOAL_RUNBOOK.md`, the active family code, and `runtime/codex_goal_state.json` if present.
2. Pick **one family + one falsifiable mechanism + one primary bottleneck**.
3. Prefer an existing project evaluator. Create/change an evaluator only when the current code cannot express the hypothesis.
4. Write a small `EXPERIMENT_SPEC.json` using `references/experiment-spec.md`.
5. Run `python tools/codex_quant_experiment.py <spec>` locally. It is CPU-first and hides CUDA/ROCm/HIP/JAX accelerators by default. Let grid/random/QMC/TPE/CMA-ES/NSGA-II/Successive-Halving/Hyperband do repetitive search locally.
6. When useful, create local scripts that batch many related checks in one process: walk-forward, purge/embargo, CPCV/CSCV, PBO, DSR/PSR, bootstrap, permutation/placebo/null tests, Monte-Carlo, sensitivity plateaus, regime splits, stress costs/slippage/latency/capacity and parameter perturbations. Prefer one long local computation plus one compact result over many model round-trips.
7. Local parallelism is allowed: multiprocessing, threads, CPU workers, vectorized numpy/scipy, SQLite-backed Optuna and queued batches may use the machine heavily. Avoid GPU unless CPU is genuinely impractical; if used outside the standard runner, record why.
8. Read `RESULT_SUMMARY.json` first. Open detailed trial/log artifacts only for a specific anomaly or scientific question. Aggregate huge outputs locally before the model reads them.
9. Decide:
   - `REJECT`: change mechanism, not cosmetic thresholds;
   - `ITERATE`: next train-only experiment with higher information value;
   - `FREEZE_CANDIDATE`: freeze before untouched OOS/forward validation;
   - `BLOCKED`: identify the missing data/code/dependency and stop wasteful model turns.

## Search budget discipline

Do **not** conserve CPU merely to conserve model quota. If a well-designed local experiment needs hundreds, thousands or more trials, run them locally. Conserve model turns, not useful computation.

Use a funnel: cheap feasibility -> coarse search -> pruning/Successive-Halving/Hyperband -> local robustness gauntlet -> freeze -> untouched OOS -> strict post-freeze forward -> final daily certification. Kill weak hypotheses early; spend large CPU budgets only on mechanisms that survived cheaper falsification.

Cache every scientific signature. Never rerun an identical expensive experiment without a changed hypothesis, code, data, seed/budget or explicit reproducibility reason.

## Scientific constraints

Count all attempted variants. Never retune on validation/OOS/forward and keep calling that segment fresh evidence. Full fees/spread/slippage/latency/capacity/liquidatability remain mandatory. `--force` is only for a recorded reproducibility/anomaly reason; a forced rerun is never automatically fresh evidence.

The +4 USD/day claim requires a real forward wall-clock duration. Never annualize or daily-normalize a few minutes of activity as proof. Missing `forward.observation_seconds`, a forward interval shorter than 86,400 seconds, or a rate below +4 USD/day => `NO_GO`.

Use external tools only for a precise missing fact/hypothesis: Exa + Parallel Search for web/practitioner evidence, Consensus for research literature, GitHub for exact code/CI/repositories. Return immediately to a local falsifiable test.

Never lower safety/economic gates to manufacture PnL. Economic certification remains owned by the machine gates, not this runner.

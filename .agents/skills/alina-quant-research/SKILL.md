---
name: alina-quant-research
description: Use when researching Alina SmartFlow edge, designing or running backtests, tuning strategy parameters, or validating/certifying copy_vault, lead_lag, or cross_venue_dislocation_v2.
---

# Alina Quant Research

## Core rule

Use model reasoning to choose **which experiment is worth running**; use the local PC to execute the repetitive search. One agent only. Never spawn/fan-out.

## Workflow

1. Read only the minimum authority needed: `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/CODEX_GOAL_RUNBOOK.md`, the active family code, and `runtime/codex_goal_state.json` if present.
2. Pick **one family + one falsifiable mechanism + one primary bottleneck**.
3. Prefer an existing project evaluator. Create/change an evaluator only when the current code cannot express the hypothesis.
4. Write a small `EXPERIMENT_SPEC.json` using `references/experiment-spec.md`.
5. Run `python tools/codex_quant_experiment.py <spec>` locally. Let grid/random/QMC/TPE/CMA-ES/NSGA-II/Successive-Halving/Hyperband do the repetitive work.
6. Read `RESULT_SUMMARY.json` first. Open detailed trial/log artifacts only for a specific anomaly or scientific question.
7. Decide:
   - `REJECT`: change mechanism, not cosmetic thresholds;
   - `ITERATE`: next train-only experiment with higher information value;
   - `FREEZE_CANDIDATE`: freeze before untouched OOS/forward validation;
   - `BLOCKED`: identify the missing data/code/dependency and stop wasteful reruns.

## Scientific constraints

Count all attempted variants. Never retune on validation/OOS/forward and keep calling that segment fresh evidence. Full fees/spread/slippage/latency/capacity/liquidatability remain mandatory. `--force` is only for a recorded reproducibility/anomaly reason; a forced rerun is never automatically fresh evidence.

Use external tools only for a precise missing fact/hypothesis: Exa + Parallel Search for web/practitioner evidence, Consensus for research literature, GitHub for exact code/CI/repositories. Return immediately to a local falsifiable test.

Never lower safety/economic gates to manufacture PnL. Economic certification remains owned by the canonical gate, not this runner.

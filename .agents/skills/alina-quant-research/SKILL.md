---
name: alina-quant-research
description: Use when researching Alina SmartFlow edge, discovering new mechanisms, designing/running backtests, tuning strategy parameters, or validating/certifying copy_vault, lead_lag, or cross_venue_dislocation_v2.
---

# Alina Quant Research — Discovery V3.1

## Core rule

Use the model as a **single quantitative research controller**. Use the local PC for every deterministic or numerical operation the PC can perform. Never spawn/fan-out to LLM subagents. Local Python processes, threads, multiprocessing, vectorized CPU jobs and long batch searches are encouraged.

The final target is **>= +4.00 USD NET per day for each canonical family separately**. The machine contract currently also requires at least **2 complete UTC proof days** in the canonical daily evidence plus the strict post-freeze forward/coverage gate. `python tools/run_daily_economic_certification.py .` remains the final authority.

## Start / resume cheaply

1. Read only `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/CODEX_GOAL_RUNBOOK.md`, the active family code and compact runtime research state.
2. Run `python tools/codex_hypothesis_ledger.py status --family <family>`.
3. If the ledger is empty, bootstrap it from the **current HEAD**, `docs/LOIS_MESUREES.md`, `tools/recherche_14h_mecanismes.py` and only the recent economic/research commits needed to represent already-tested mechanisms. Register those records with `baseline=true`.
4. If HEAD advanced since the latest recorded `base_sha`, inspect only the new relevant commits and register genuinely new/revised mechanism lineages before scoring novelty. Do not rescan all Git history.
5. Recent Lead-Lag maker/taker/streaming work, Cross-Venue V5 and current Copy-Vault proof/strategy lineages are existing work, not automatic novelty merely because the V3 ledger started later.

## Controller loop

The controller chooses one of `IMPROVE`, `COMBINE`, `PIVOT`, `STOP` from evidence, never from narrative momentum.

### DISCOVERY

Enter Discovery at the start of a fresh family cycle, when `needs-rediscovery` says so, or for a champion-challenger novelty check.

Read `references/discovery-v31.md` **only while doing Discovery/champion-challenger work**; do not keep rereading it during ordinary backtests.

- Default to **12 structurally distinct hypotheses**; the hard minimum is 8. Aim for at least 5 distinct mechanism archetypes rather than cosmetic variants.
- Each hypothesis must specify mechanism, data surfaces, temporal operator, conditioning/regime, prediction target, executable translation, rationale and a falsification test.
- Register/score it with `tools/codex_hypothesis_ledger.py`; semantic duplicates do not count toward the pool.
- The ten mechanisms in `tools/recherche_14h_mecanismes.py` are historical baselines. Existing maker/taker timing, streaming, Cross-Venue V5 and Copy-Vault lineages are also baselines unless the new hypothesis changes the mechanism materially.
- Treat rejected/stalled lineages as negative memory: do not revisit them without new data, a new data surface, a materially new causal mechanism or an explicit contradiction in fresh evidence.
- A Discovery cycle may proactively run one grouped external research pass: Exa + Parallel Search for practitioner/web evidence, Consensus for literature, GitHub for code/repositories, and CoinGecko only for current-regime context. Search for mechanisms missing from the ledger, not confirmation of the incumbent. External context must become a local falsifiable hypothesis; it is never economic proof.

Good search regions include, without limiting the controller: wallet informativeness/toxicity and cross-venue anticipation; wallet × L2/order-flow interactions; asynchronous price discovery; cross-asset spillovers; event-time representations; Hawkes/VAR/VECM/transfer-entropy when data supports them; regime-conditioned microstructure; liquidation/OI/basis/funding interactions; calibrated probability/quantile/hazard targets; simple and nonlinear CPU models whose incremental OOS value can be measured.

### TOURNAMENT

Before a large search budget, cheaply falsify/rank the new hypotheses on **novelty, causal plausibility, data availability, executable headroom after costs, expected information gain and falsification cost**.

Use local scripts/batches. Prefer evidence that a mechanism predicts an actionable future distribution: direction, move probability/magnitude, quantiles, time-to-move/hazard, horizon/timing and expected **NET** edge after execution. Accuracy/R²/IC alone never wins a tournament.

### EXPLOIT

Spend large local CPU budgets only on tournament survivors.

For one campaign:
`EXPERIMENT_SPEC.json -> python tools/codex_quant_experiment.py <spec> -> RESULT_SUMMARY.json`

For several predeclared campaigns:
`BATCH_SPEC.json -> python tools/codex_quant_batch.py <batch> -> BATCH_SUMMARY.json`

Use existing grid/random/QMC/TPE/Optuna/CMA-ES/NSGA-II/Successive-Halving/Hyperband and any justified project-local CPU analysis. Batch walk-forward, purge/embargo, CPCV/CSCV, PBO, DSR/PSR, bootstrap, permutations/placebos/nulls, Monte-Carlo, sensitivity plateaus, regime splits and execution stress when scientifically relevant. The PC may run hundreds, thousands or more trials. Do not return to the model between trials that can be predeclared.

Escalate model complexity only when a simpler falsification/baseline survives: event-study/conditional statistics -> linear/probabilistic/time-series methods -> nonlinear CPU models -> regime mixtures/ensembles. Every extra layer must add OOS economic value after costs.

Read compact summaries first. Keep detailed trials, SQLite and large logs on disk; aggregate locally before model inspection.

### REDISCOVERY / ANTI-LOOP

After each material result, record the experiment IDs/signatures/trial count and economic progress in the ledger.

Run:
`python tools/codex_hypothesis_ledger.py needs-rediscovery <hypothesis_id>`
`python tools/codex_hypothesis_ledger.py needs-challenger <hypothesis_id>`

Return to Discovery when:
- two consecutive comparable iterations are only `PARAMETER_ONLY` without positive economic progress;
- two consecutive evaluations retain non-positive executable headroom or reject the mechanism;
- a candidate is a semantic duplicate of exhausted history;
- the controller has no new causal reason for another retune.

**Novelty injection:** after 3 consecutive `IMPROVE` decisions on one lineage without `FREEZE`, run a mini-Discovery with >=4 orthogonal challengers before a fourth local improvement. The incumbent may continue if it beats the challengers; this is not an automatic kill.

When progress is real, `IMPROVE` may continue. `COMBINE` may recombine complementary mechanisms/data surfaces while keeping final family attribution and certification separate. `PIVOT` opens a new mechanism. `STOP` ends only the exhausted lineage, not the global +4/day mission.

## Scientific constraints

Count **all** tried variants. Search feedback must remain disjoint from final held-out evidence. Validation/OOS/forward observed and then used for retuning becomes exploratory; refreeze and obtain new disjoint evidence.

Full fees, spread, slippage, latency, capacity, fill/liquidatability, positions closed, provenance and no-lookahead remain mandatory. Never lower a safety/economic gate to create a PASS.

The canonical objective currently requires at least 2 completed UTC proof days at the daily threshold; the final daily certification additionally requires verified strict post-freeze forward wall-clock coverage and rate. Always follow the exact current machine gates if they evolve.

## Quota / compute policy

Conserve **model turns**, not CPU.

- GPT-5.6 Sol High/Élevé, Standard, Fast OFF.
- One LLM controller only; no subagents/reviewer agents.
- CPU-first. The standard runner hides CUDA/ROCm/HIP/JAX accelerators by default.
- Use GPU only when CPU is demonstrably impractical and the reason is recorded.
- If 1,000 calculations can run locally without an intermediate decision, run them in one script/batch.
- Cache scientific signatures; do not repeat identical heavy runs without changed code/data/hypothesis/seed/budget or a recorded reproducibility reason.

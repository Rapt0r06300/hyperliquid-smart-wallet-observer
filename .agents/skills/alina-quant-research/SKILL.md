---
name: alina-quant-research
description: Use for Alina SmartFlow quantitative edge discovery, backtests, tuning, falsification, OOS/forward validation, and certification of copy_vault, lead_lag, or cross_venue_dislocation_v2.
---

# Alina Quant Research — Discovery V3.2

## Start / resume

Run first: `python tools/codex_research_context.py --auto`.
Treat its compact JSON as the default resume state. **Ne pas rescanner** Git complet, les 775 optimisations scellées, tout le dépôt ou de gros logs pour reconstruire le contexte. Si HEAD change, inspecter uniquement le delta pertinent depuis `base_sha`.

`HYPOTHESIS_LEDGER.jsonl` et `PROCESS_MEMORY.jsonl` sont append-only. Historical memory is guidance only, never certification.

## Core rule

One LLM controller; no LLM subagents inside an economic Discovery campaign. The PC does every deterministic calculation it can: Python, numpy/scipy, pytest, replay, backtest, bootstrap, permutations, Monte-Carlo, optimization, profiling and aggregation. CPU-first, local parallelism allowed. Model turns are scarce; CPU is not quota.

Preferred cadence: `1 model decision -> large local batch -> compact summary -> 1 model decision`.

## DISCOVERY

Enter on a fresh family cycle, `needs-rediscovery`, PIVOT, or champion-challenger event. Read `references/discovery-v32.md` only then.

Default 12 structurally distinct hypotheses; hard minimum 8; target >=5 mechanism archetypes. `PARAMETER_ONLY` changes do not count as new hypotheses.

Before spending model turns enumerating combinations, use:
`python tools/codex_semantic_discovery.py --family <family> --pool-size 2000 --shortlist 12`.

The semantic engine expands locally, rejects invalid combinations, filters exact/near duplicates and high-confidence process-memory vetoes, applies bounded positive priors, scores research priority, and returns only a diverse shortlist. Search score is not economic proof.

Each realized hypothesis still needs mechanism, data surfaces, temporal operator, conditioning/regime, actionable future target, paper execution translation, rationale and falsification test. Register it in `hypothesis_ledger`.

## TOURNAMENT

Cheaply falsify first. Rank novelty, causal plausibility, available data, executable NET headroom, information gain and falsification cost. Accuracy/R2/IC alone never wins; prefer actionable markout distributions/quantiles, move probability/magnitude, hazard/time-to-move, fill/adverse-selection, or expected NET edge.

## EXPLOIT

Spend heavy local CPU only on survivors. Use `codex_quant_experiment.py` for one campaign or `codex_quant_batch.py` for many predefined campaigns. Batch without internal model round-trips; read `RESULT_SUMMARY.json` / `BATCH_SUMMARY.json` before detailed trials.

Escalate complexity only if simple baselines survive and each layer adds OOS economic value after costs.

## REDISCOVERY / challenger

After each material result record signatures, experiment IDs, `trial_count`, economic progress and one action: `IMPROVE`, `COMBINE`, `PIVOT`, `STOP`.

Run `needs-rediscovery`: two comparable `PARAMETER_ONLY` retunes without positive progress, or two rejected/non-positive-headroom evaluations, force PIVOT.
Run `needs-challenger`: after 3 consecutive `IMPROVE` decisions without FREEZE, test >=4 orthogonal challengers before a fourth local improve.

High-confidence negative memory may veto only a sufficiently equivalent mechanism+context after repeated evidence. Retest is allowed with genuinely new data/surface, materially different causality, or contradictory fresh evidence. Positive memory is bounded and non-certifying.

## Scientific / safety contract

All tried variants count toward search pressure. Search/feedback evidence is disjoint from final held-out proof. OOS/forward observed then used to retune becomes exploratory; refreeze and collect new disjoint proof.

Final target remains >= +4.00 USD NET/day **for each canonical family separately**, with exact-HEAD machine gates, costs, liquidatability, closed positions, provenance, no-lookahead and strict post-freeze forward. `python tools/run_daily_economic_certification.py .` is final authority.

Never route/sign/submit exchange orders, handle keys, deposits or withdrawals. Paper/read-only only; fail closed.

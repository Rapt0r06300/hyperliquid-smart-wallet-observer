# `EXPERIMENT_SPEC.json` reference

Minimal schema for `python tools/codex_quant_experiment.py SPEC.json`.

```json
{
  "schema_version": 1,
  "experiment_id": "ll-latency-001",
  "family": "lead_lag",
  "hypothesis_id": "H-LL-latency-decay",
  "phase": "train_search",
  "base_sha": "0123456789abcdef0123456789abcdef01234567",
  "data_fingerprint": "sha256:<dataset-or-manifest-fingerprint>",
  "data_cutoff_utc": "2026-09-09T17:00:00Z",
  "evaluator": "hl_observer.some_module:evaluate_candidate",
  "search_space": {
    "lag_ms": [50, 100, 150],
    "threshold_bps": {"min": 1.0, "max": 8.0}
  },
  "engine": "tpe",
  "budget": {"max_trials": 200},
  "seed": 17,
  "cost_model": {
    "taker_bps_per_leg": 4.5,
    "slippage": "book_vwap"
  },
  "split_config": {
    "kind": "purged_walk_forward",
    "embargo_ms": 250
  },
  "metadata": {"note": "train only"}
}
```

## Allowed values

`family`: `copy_vault`, `lead_lag`, `cross_venue_dislocation_v2`.

`phase`: `feasibility`, `train_search`, `sensitivity`, `walk_forward`, `anti_overfit`, `oos`, `forward`, `certification`.

`engine`: `grid`, `random`, `qmc`, `tpe`, `cma_es`, `nsga2`, `successive_halving`, `hyperband`.

`evaluator` must be project-local: `hl_observer.*:<callable>` or `tools.*:<callable>`.

## Evaluator contract

The callable receives `params` and may optionally accept keyword arguments `budget` and `context`:

```python
def evaluate_candidate(params: dict, *, budget: float = 1.0, context: dict | None = None) -> dict:
    return {
        "net_usd": 0.0,
        "pf": 1.0,
        "candidate_verdict": "ITERATE"
    }
```

Return finite JSON-compatible metrics. `candidate_verdict` may be `REJECT`, `ITERATE`, `FREEZE_CANDIDATE`, or `BLOCKED`. It is a research suggestion, never the final economic certification.

## Identity and cache

The scientific signature hashes the SHA, family, hypothesis, phase, data fingerprint/cutoff, evaluator, search space, engine, budget, seed, cost model and split configuration. An identical completed signature returns the cached compact result rather than rerunning trials.

`--force --reason "..."` creates a separate rerun only for a documented anomaly/reproducibility need. It never makes already-seen OOS/forward data fresh again.

## Outputs

Detailed local artifacts: `runtime/codex_experiments/<run_id>/`.

Read first: `RESULT_SUMMARY.json`. The runner also updates `runtime/codex_goal_state.json` with the minimal resume state.

`budget.max_trials` is the hard trial-count bound passed to the existing optimizer. `max_wall_seconds`, when present, is recorded by V2 but is not claimed as a hard-kill guarantee; check `wall_budget_enforced` in the summary.

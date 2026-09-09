from __future__ import annotations

from pathlib import Path

from tools.codex_quant_batch import run_batch


def _spec(experiment_id: str) -> dict:
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "family": "lead_lag",
        "hypothesis_id": f"H-{experiment_id}",
        "phase": "train_search",
        "base_sha": "a" * 40,
        "data_fingerprint": "sha256:batch-data",
        "data_cutoff_utc": "2026-09-09T18:00:00Z",
        "evaluator": "hl_observer.fake_batch:evaluate",
        "search_space": {"x": [1, 2]},
        "engine": "tpe",
        "budget": {"max_trials": 20, "max_wall_seconds": 60},
        "seed": 1,
        "cost_model": {"fees": "canonical"},
        "split_config": {"kind": "purged_walk_forward"},
    }


def test_batch_runs_many_local_experiments_without_model_roundtrips(tmp_path: Path) -> None:
    calls: list[str] = []

    def runner(spec, *, runtime_root, current_sha=None, repo_root=None):
        calls.append(spec.experiment_id)
        return {
            "experiment_id": spec.experiment_id,
            "signature": spec.signature(),
            "verdict": "ITERATE",
            "cache_hit": False,
            "compute_policy": {"local_compute": True, "device": "cpu"},
        }

    result = run_batch(
        {
            "schema_version": 1,
            "batch_id": "lead-lag-gauntlet-001",
            "experiments": [_spec("exp-1"), _spec("exp-2"), _spec("exp-3")],
        },
        runtime_root=tmp_path / "codex_experiments",
        runner=runner,
        current_sha="a" * 40,
    )

    assert calls == ["exp-1", "exp-2", "exp-3"]
    assert result["experiments_total"] == 3
    assert result["experiments_completed"] == 3
    assert result["local_compute"] is True
    assert result["model_roundtrips_required_inside_batch"] == 0
    assert len(result["results"]) == 3

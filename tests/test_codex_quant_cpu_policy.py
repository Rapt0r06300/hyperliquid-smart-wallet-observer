from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from hl_observer.research.experiment_protocol import ExperimentSpec
from tools.codex_quant_experiment import run_experiment


def _spec() -> ExperimentSpec:
    return ExperimentSpec.from_mapping(
        {
            "schema_version": 1,
            "experiment_id": "cpu-policy-001",
            "family": "lead_lag",
            "hypothesis_id": "H-CPU-LOCAL",
            "phase": "train_search",
            "base_sha": "a" * 40,
            "data_fingerprint": "sha256:cpu-policy",
            "data_cutoff_utc": "2026-09-09T18:00:00Z",
            "evaluator": "hl_observer.fake_cpu_policy:evaluate",
            "search_space": {"threshold": [1.0, 2.0]},
            "engine": "random",
            "budget": {"max_trials": 2, "max_wall_seconds": 30},
            "seed": 1,
            "cost_model": {"fees": "canonical"},
            "split_config": {"kind": "train_only"},
        }
    )


def test_local_quant_runner_is_cpu_first_and_hides_gpu_by_default(tmp_path: Path) -> None:
    module = types.ModuleType("hl_observer.fake_cpu_policy")

    def evaluate(params: dict, *, budget: float = 1.0, context: dict | None = None) -> dict:
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""
        assert os.environ.get("ROCR_VISIBLE_DEVICES") == ""
        assert os.environ.get("HIP_VISIBLE_DEVICES") == ""
        assert os.environ.get("JAX_PLATFORM_NAME") == "cpu"
        assert int(os.environ.get("ALINA_CPU_WORKERS", "0")) >= 1
        return {"net_usd": 1.0, "candidate_verdict": "ITERATE"}

    module.evaluate = evaluate
    sys.modules[module.__name__] = module

    def optimizer(evaluer_params, espace, *, outil, n_trials, storage_dir, seed):
        metrics = evaluer_params({"threshold": 1.0}, budget=1.0)
        return {
            "disponible": True,
            "lance": True,
            "trials_proposes": n_trials,
            "trials_termines": 1,
            "trials_prunes": 0,
            "trials_echoues": 0,
            "meilleur_score": 1.0,
            "meilleur": {"params": {"threshold": 1.0}, "metriques": metrics},
        }

    summary = run_experiment(
        _spec(),
        runtime_root=tmp_path / "codex_experiments",
        optimizer=optimizer,
        current_sha="a" * 40,
    )

    assert summary["compute_policy"]["device"] == "cpu"
    assert summary["compute_policy"]["gpu_allowed"] is False
    assert summary["compute_policy"]["cpu_workers"] >= 1
    assert summary["compute_policy"]["local_compute"] is True

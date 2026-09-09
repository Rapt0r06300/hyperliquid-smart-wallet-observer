from __future__ import annotations

import json
import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

from hl_observer.research.experiment_protocol import (
    ExperimentSpec,
    SpecValidationError,
    load_cached_summary,
    write_goal_state_atomic,
    write_summary_atomic,
)
from tools.codex_quant_experiment import run_experiment


def spec_payload() -> dict:
    return {
        "schema_version": 1,
        "experiment_id": "ll-latency-001",
        "family": "lead_lag",
        "hypothesis_id": "H-LL-latency-decay",
        "phase": "train_search",
        "base_sha": "a" * 40,
        "data_fingerprint": "sha256:data-v1",
        "data_cutoff_utc": "2026-09-09T17:00:00Z",
        "evaluator": "hl_observer.fake_quant:evaluate",
        "search_space": {
            "lag_ms": [50, 100, 150],
            "threshold_bps": {"min": 1.0, "max": 8.0},
        },
        "engine": "tpe",
        "budget": {"max_trials": 24, "max_wall_seconds": 120},
        "seed": 17,
        "cost_model": {"taker_bps_per_leg": 4.5, "slippage": "book_vwap"},
        "split_config": {"kind": "purged_walk_forward", "embargo_ms": 250},
        "metadata": {"note": "train only"},
    }


def test_spec_validates_and_signature_is_deterministic() -> None:
    first = ExperimentSpec.from_mapping(spec_payload())
    second = ExperimentSpec.from_mapping(deepcopy(spec_payload()))
    assert first.signature() == second.signature()
    assert len(first.signature()) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("family", "funding_carry"),
        ("phase", "magic"),
        ("engine", "brute_force_forever"),
        ("evaluator", "tests.fake:evaluate"),
        ("experiment_id", "../escape"),
        ("data_fingerprint", ""),
        ("cost_model", {}),
        ("split_config", {}),
    ],
)
def test_spec_rejects_invalid_scientific_contract(field: str, value: object) -> None:
    payload = spec_payload()
    payload[field] = value
    with pytest.raises(SpecValidationError):
        ExperimentSpec.from_mapping(payload)


def test_spec_rejects_missing_required_field() -> None:
    payload = spec_payload()
    payload.pop("cost_model")
    with pytest.raises(SpecValidationError, match="cost_model"):
        ExperimentSpec.from_mapping(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_sha", "b" * 40),
        ("data_fingerprint", "sha256:data-v2"),
        ("seed", 99),
        ("engine", "random"),
        ("search_space", {"lag_ms": [20, 40]}),
        ("cost_model", {"taker_bps_per_leg": 5.0}),
        ("split_config", {"kind": "anchored_walk_forward"}),
        ("budget", {"max_trials": 48}),
    ],
)
def test_signature_changes_when_scientific_input_changes(field: str, value: object) -> None:
    base = ExperimentSpec.from_mapping(spec_payload()).signature()
    changed = spec_payload()
    changed[field] = value
    assert ExperimentSpec.from_mapping(changed).signature() != base


def test_atomic_json_writes_and_cache_lookup(tmp_path: Path) -> None:
    summary_path = tmp_path / "exp" / "RESULT_SUMMARY.json"
    goal_state = tmp_path / "codex_goal_state.json"
    summary = {"signature": "abc", "verdict": "ITERATE"}
    write_summary_atomic(summary_path, summary)
    write_goal_state_atomic(goal_state, {"family": "lead_lag", "phase": "train_search"})
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary
    assert json.loads(goal_state.read_text(encoding="utf-8"))["family"] == "lead_lag"

    cache = tmp_path / "_cache" / "abc.json"
    write_summary_atomic(cache, summary)
    assert load_cached_summary(tmp_path, "abc") == summary


def _install_fake_evaluator() -> dict[str, int]:
    calls = {"count": 0}
    module = types.ModuleType("hl_observer.fake_quant")

    def evaluate(params: dict, *, budget: float = 1.0, context: dict | None = None) -> dict:
        calls["count"] += 1
        assert context is not None
        assert context["family"] == "lead_lag"
        return {
            "net_usd": float(params.get("score", 1.0)) * budget,
            "pf": 1.2,
            "candidate_verdict": "FREEZE_CANDIDATE" if budget == 1.0 else "ITERATE",
        }

    module.evaluate = evaluate
    sys.modules[module.__name__] = module
    return calls


def test_run_experiment_delegates_trials_and_writes_compact_summary(tmp_path: Path) -> None:
    calls = _install_fake_evaluator()
    spec = ExperimentSpec.from_mapping(spec_payload())
    seen: dict = {}

    def optimizer(evaluer_params, espace, *, outil, n_trials, storage_dir, seed):
        seen.update(
            {
                "space": espace,
                "engine": outil,
                "n_trials": n_trials,
                "storage_dir": Path(storage_dir),
                "seed": seed,
            }
        )
        metrics = evaluer_params({"score": 3.0}, budget=1.0)
        return {
            "outil": outil,
            "disponible": True,
            "lance": True,
            "trials_proposes": n_trials,
            "trials_termines": n_trials - 3,
            "trials_prunes": 2,
            "trials_echoues": 1,
            "meilleur_score": 3.5,
            "meilleur": {"params": {"score": 3.0}, "metriques": metrics},
            "cpu_s": 0.25,
        }

    summary = run_experiment(
        spec,
        runtime_root=tmp_path / "codex_experiments",
        optimizer=optimizer,
        current_sha="a" * 40,
    )

    assert calls["count"] == 1
    assert seen["engine"] == "tpe"
    assert seen["n_trials"] == 24
    assert seen["seed"] == 17
    assert seen["space"] == spec.search_space
    assert summary["trials"] == {"proposed": 24, "completed": 21, "pruned": 2, "failed": 1}
    assert summary["verdict"] == "FREEZE_CANDIDATE"
    assert summary["best_candidate"]["metrics"]["net_usd"] == 3.0
    assert summary["cache_hit"] is False

    result_path = Path(summary["artifacts"]["summary"])
    detail_path = Path(summary["artifacts"]["optimizer_result"])
    assert result_path.exists()
    assert detail_path.exists()
    persisted = json.loads(result_path.read_text(encoding="utf-8"))
    assert persisted["signature"] == spec.signature()
    assert len(result_path.read_text(encoding="utf-8")) < 12_000

    state_path = tmp_path / "codex_goal_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["last_result_signature"] == spec.signature()
    assert state["next_action"] == "review_result_summary"


def test_identical_signature_uses_cache_without_rerun(tmp_path: Path) -> None:
    _install_fake_evaluator()
    spec = ExperimentSpec.from_mapping(spec_payload())
    invocations = {"count": 0}

    def optimizer(*args, **kwargs):
        invocations["count"] += 1
        return {
            "disponible": True,
            "lance": True,
            "trials_proposes": 1,
            "trials_termines": 1,
            "trials_prunes": 0,
            "trials_echoues": 0,
            "meilleur_score": 1.0,
            "meilleur": {"params": {}, "metriques": {"candidate_verdict": "ITERATE"}},
        }

    root = tmp_path / "codex_experiments"
    first = run_experiment(spec, runtime_root=root, optimizer=optimizer, current_sha="a" * 40)
    second = run_experiment(spec, runtime_root=root, optimizer=optimizer, current_sha="a" * 40)
    assert invocations["count"] == 1
    assert first["signature"] == second["signature"]
    assert second["cache_hit"] is True


def test_force_requires_reason_and_records_forced_rerun(tmp_path: Path) -> None:
    _install_fake_evaluator()
    spec = ExperimentSpec.from_mapping(spec_payload())

    def optimizer(*args, **kwargs):
        return {
            "disponible": True,
            "lance": True,
            "trials_proposes": 1,
            "trials_termines": 1,
            "trials_prunes": 0,
            "trials_echoues": 0,
            "meilleur_score": 1.0,
            "meilleur": {"params": {}, "metriques": {"candidate_verdict": "ITERATE"}},
        }

    root = tmp_path / "codex_experiments"
    run_experiment(spec, runtime_root=root, optimizer=optimizer, current_sha="a" * 40)
    with pytest.raises(SpecValidationError, match="force reason"):
        run_experiment(
            spec, runtime_root=root, optimizer=optimizer, current_sha="a" * 40, force=True
        )

    forced = run_experiment(
        spec,
        runtime_root=root,
        optimizer=optimizer,
        current_sha="a" * 40,
        force=True,
        force_reason="reproduce deterministic runtime anomaly",
    )
    assert forced["forced"] is True
    assert forced["force_reason"] == "reproduce deterministic runtime anomaly"
    assert forced["fresh_evidence_claim"] is False


def test_run_refuses_base_sha_mismatch(tmp_path: Path) -> None:
    _install_fake_evaluator()
    spec = ExperimentSpec.from_mapping(spec_payload())
    with pytest.raises(SpecValidationError, match="base_sha"):
        run_experiment(
            spec,
            runtime_root=tmp_path / "codex_experiments",
            optimizer=lambda *a, **k: {},
            current_sha="b" * 40,
        )


def test_atomic_writer_accepts_numpy_scalars_without_stringifying_numbers(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    path = tmp_path / "numpy.json"
    write_summary_atomic(path, {"count": np.int64(7), "score": np.float64(1.25)})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"count": 7, "score": 1.25}


def test_existing_uncached_run_directory_is_not_overwritten(tmp_path: Path) -> None:
    _install_fake_evaluator()
    spec = ExperimentSpec.from_mapping(spec_payload())
    root = tmp_path / "codex_experiments"
    run_dir = root / spec.experiment_id
    run_dir.mkdir(parents=True)
    sentinel = run_dir / "OPTIMIZER_RESULT.json"
    sentinel.write_text('{"old": true}\n', encoding="utf-8")

    with pytest.raises(SpecValidationError, match="existing experiment directory"):
        run_experiment(
            spec,
            runtime_root=root,
            optimizer=lambda *a, **k: {},
            current_sha="a" * 40,
        )
    assert json.loads(sentinel.read_text(encoding="utf-8")) == {"old": True}

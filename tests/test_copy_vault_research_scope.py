from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from hl_observer.research.experiment_protocol import ExperimentSpec, SpecValidationError
from hl_observer.research.hypothesis_ledger import (
    HypothesisValidationError,
    append_record,
    load_records,
    validate_record,
)
from hl_observer.research.process_memory import (
    ProcessMemoryValidationError,
    append_process_record,
    candidate_memory_effect,
    load_process_records,
    validate_process_record,
)
from hl_observer.research.research_context import build_research_context
from hl_observer.research.semantic_discovery import (
    generate_semantic_plans,
    load_catalog,
    rank_semantic_plans,
)
from hl_observer.strategies.active_scope import active_strategy_families
from tools.codex_quant_experiment import run_experiment

ROOT = Path(__file__).resolve().parents[1]


def _hypothesis(family: str, record_id: str) -> dict:
    return {
        "schema_version": 1,
        "record_id": record_id,
        "created_at_utc": "2026-10-27T12:00:00Z",
        "hypothesis_id": f"H-{record_id}",
        "family": family,
        "stage": "DISCOVERY",
        "mechanism": "leader fill predicts executable Copy-Vault markout",
        "data_surfaces": ["copy_vault_leader_fills", "hl_l2"],
        "temporal_operator": "causal event time",
        "conditioning": ["liquid regime"],
        "prediction_target": "net executable markout",
        "execution_translation": "paper Copy-Vault replay",
        "change_class": "NEW_MECHANISM",
        "rationale": "scope regression fixture",
        "falsification_test": "reject when held-out net headroom is not positive",
        "trial_count": 0,
    }


def _process_memory(family: str, record_id: str) -> dict:
    return {
        "record_id": record_id,
        "family": family,
        "mechanism_signature": "historical-mechanism",
        "context": ["historical"],
        "change_motif": "archived",
        "outcome": "FAILURE",
        "evidence_count": 2,
        "confidence": 0.5,
        "failure_reason": "historical fixture",
        "success_evidence": None,
        "provenance": "historical",
        "certifying": False,
        "retest_condition": "new evidence",
    }


def _experiment(family: str) -> dict:
    return {
        "schema_version": 1,
        "experiment_id": "scope-check-001",
        "family": family,
        "hypothesis_id": "H-scope-check",
        "phase": "train_search",
        "base_sha": "a" * 40,
        "data_fingerprint": "sha256:scope-fixture",
        "data_cutoff_utc": "2026-10-27T12:00:00Z",
        "evaluator": "hl_observer.fake:evaluate",
        "search_space": {"threshold": [1, 2]},
        "engine": "grid",
        "budget": {"max_trials": 2},
        "seed": 1,
        "cost_model": {"fees": "observed"},
        "split_config": {"kind": "purged_walk_forward"},
    }


def _run_tool(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(ROOT / "tools" / script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_auto_research_context_never_selects_underworked_disabled_family(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            json.dumps(validate_record(_hypothesis("copy_vault", f"R-{index}")))
            for index in range(5)
        )
        + "\n",
        encoding="utf-8",
    )

    context = build_research_context(tmp_path, ledger_path=ledger)

    assert context["family"] == "copy_vault"


@pytest.mark.parametrize("family", ["lead_lag", "cross_venue_dislocation_v2"])
def test_research_context_refuses_explicit_disabled_family(family: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        build_research_context(tmp_path, family=family)


def test_semantic_generation_and_ranking_refuse_disabled_families() -> None:
    catalog = load_catalog(
        ROOT / ".agents/skills/alina-quant-research/references/semantic-catalog-v32.json"
    )
    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        generate_semantic_plans(catalog, "lead_lag", 10, 1)

    disabled = generate_semantic_plans(catalog, "copy_vault", 10, 1)[0]
    disabled["family"] = "cross_venue_dislocation_v2"
    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        rank_semantic_plans([disabled], [], [], 1)


def test_semantic_catalog_marks_legacy_axes_archived_and_rejects_scope_drift(
    tmp_path: Path,
) -> None:
    catalog_path = ROOT / ".agents/skills/alina-quant-research/references/semantic-catalog-v32.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert payload["active_families"] == ["copy_vault"]
    assert set(payload["archived_families"]) == {
        "lead_lag",
        "cross_venue_dislocation_v2",
    }
    load_catalog(catalog_path)

    payload["active_families"] = ["copy_vault", "lead_lag"]
    drifted = tmp_path / "catalog-drift.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="active family scope"):
        load_catalog(drifted)


@pytest.mark.parametrize("family", ["lead_lag", "cross_venue_dislocation_v2"])
def test_experiment_specs_refuse_disabled_economic_families(family: str) -> None:
    with pytest.raises(SpecValidationError, match="DISABLED_BY_SCOPE"):
        ExperimentSpec.from_mapping(_experiment(family))


def test_environment_cannot_expand_active_research_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALINA_ACTIVE_STRATEGIES", "lead_lag,cross_venue_dislocation_v2")

    assert active_strategy_families() == frozenset({"copy_vault"})
    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        generate_semantic_plans(
            load_catalog(
                ROOT / ".agents/skills/alina-quant-research/references/semantic-catalog-v32.json"
            ),
            "lead_lag",
            5,
            0,
        )


@pytest.mark.parametrize("family", ["lead_lag", "cross_venue_dislocation_v2"])
def test_new_process_memory_scoring_refuses_disabled_candidates(family: str) -> None:
    with pytest.raises(ProcessMemoryValidationError, match="DISABLED_BY_SCOPE"):
        candidate_memory_effect(
            {
                "family": family,
                "mechanism_signature": "archived-mechanism",
                "context": ["archived"],
            },
            [],
        )


def test_manually_constructed_disabled_experiment_cannot_run_or_write(tmp_path: Path) -> None:
    spec = replace(ExperimentSpec.from_mapping(_experiment("copy_vault")), family="lead_lag")
    optimizer_called = False

    def optimizer(*args, **kwargs):
        nonlocal optimizer_called
        optimizer_called = True
        raise AssertionError("disabled family reached optimizer")

    with pytest.raises(SpecValidationError, match="DISABLED_BY_SCOPE"):
        run_experiment(
            spec,
            runtime_root=tmp_path / "experiments",
            optimizer=optimizer,
            current_sha="a" * 40,
        )
    assert not optimizer_called
    assert not (tmp_path / "experiments").exists()


@pytest.mark.parametrize("family", ["lead_lag", "cross_venue_dislocation_v2"])
def test_new_hypothesis_writes_refuse_disabled_family_but_history_remains_readable(
    family: str, tmp_path: Path
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    historical = validate_record(_hypothesis(family, "R-OLD"))
    ledger.write_text(json.dumps(historical) + "\n", encoding="utf-8")

    assert load_records(ledger) == [historical]
    with pytest.raises(HypothesisValidationError, match="DISABLED_BY_SCOPE"):
        append_record(ledger, _hypothesis(family, "R-NEW"))
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

    memory_path = tmp_path / "memory.jsonl"
    old_memory = validate_process_record(_process_memory(family, "PM-OLD"))
    memory_path.write_text(json.dumps(old_memory) + "\n", encoding="utf-8")
    assert load_process_records(memory_path) == [old_memory]
    with pytest.raises(ProcessMemoryValidationError, match="DISABLED_BY_SCOPE"):
        append_process_record(memory_path, _process_memory(family, "PM-NEW"))
    assert len(memory_path.read_text(encoding="utf-8").splitlines()) == 1


def test_research_context_cli_refuses_disabled_family_without_writing_output(tmp_path: Path) -> None:
    output = tmp_path / "context.json"
    result = _run_tool("codex_research_context.py", "--family", "lead_lag", "--out", str(output))

    assert result.returncode == 2
    assert "DISABLED_BY_SCOPE" in result.stderr
    assert not output.exists()


def test_semantic_cli_refuses_disabled_family_without_writing_any_artifact(tmp_path: Path) -> None:
    output = tmp_path / "shortlist.json"
    status = tmp_path / "status.json"
    result = _run_tool(
        "codex_semantic_discovery.py",
        "--family",
        "lead_lag",
        "--out",
        str(output),
        "--status-out",
        str(status),
    )

    assert result.returncode == 2
    assert "DISABLED_BY_SCOPE" in result.stderr
    assert not output.exists()
    assert not status.exists()


def test_hypothesis_ledger_cli_blocks_disabled_writes_but_reads_legacy_status(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    historical = validate_record(_hypothesis("lead_lag", "R-OLD"))
    ledger.write_text(json.dumps(historical) + "\n", encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(_hypothesis("lead_lag", "R-NEW")), encoding="utf-8")

    register = _run_tool(
        "codex_hypothesis_ledger.py", "--ledger", str(ledger), "register", str(candidate)
    )
    assert register.returncode == 2
    assert "DISABLED_BY_SCOPE" in register.stderr
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

    score = _run_tool(
        "codex_hypothesis_ledger.py", "--ledger", str(ledger), "score", str(candidate)
    )
    assert score.returncode == 2
    assert "DISABLED_BY_SCOPE" in score.stderr
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

    status = _run_tool(
        "codex_hypothesis_ledger.py",
        "--ledger",
        str(ledger),
        "status",
        "--family",
        "lead_lag",
    )
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["records"] == 1

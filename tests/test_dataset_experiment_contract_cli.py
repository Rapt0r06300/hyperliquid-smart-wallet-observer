from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

from hl_observer.datasets.experiment_contract import CURRENT_REPLAY_INPUT_CONTRACT
from hl_observer.datasets.experiment_plan import CURRENT_EXPERIMENT_PLAN
import hl_observer.ops.dataset_experiment_contract as contract_cli
from hl_observer.ops.dataset_experiment_contract import main


def _write_plan(root: Path, *, status: str = "READY") -> None:
    path = root / CURRENT_EXPERIMENT_PLAN
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "experiment_digest": "a" * 64,
                "criteria": {"family": "lead_lag", "coin": "BTC"},
                "provenance": {
                    "status": "READY",
                    "source_release_id": 371149058,
                    "suite": "research-lab-full",
                    "selection_digest": "b" * 64,
                },
                "research_lab": {
                    "files": [
                        {
                            "relative_path": "runtime/research_lab/lead.jsonl",
                            "timestamp_min_ms": 1000,
                            "timestamp_max_ms": 2000,
                            "complete": True,
                            "selection_uncertain": False,
                        }
                    ]
                },
                "sqlite": {"selected": []},
            }
        ),
        encoding="utf-8",
    )


def test_cli_contrat_ecrit_un_contrat_read_only(tmp_path: Path) -> None:
    _write_plan(tmp_path)

    code = main(["--root", str(tmp_path)])

    assert code == 0
    current = tmp_path / CURRENT_REPLAY_INPUT_CONTRACT
    assert current.is_file()
    payload = json.loads(current.read_text(encoding="utf-8"))
    assert payload["source_count"] == 1
    assert payload["read_only"] is True
    assert payload["network_used"] is False
    assert payload["raw_data_embedded"] is False


def test_cli_contrat_refuse_un_plan_non_ready(tmp_path: Path) -> None:
    _write_plan(tmp_path, status="NO_MATCH")
    assert main(["--root", str(tmp_path)]) == 2


def test_cli_contrat_refuse_un_workspace_sans_plan(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path)]) == 2


def test_module_entrypoint_ecrit_un_contrat_read_only(tmp_path: Path, monkeypatch) -> None:
    _write_plan(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["dataset_experiment_contract", "--root", str(tmp_path)],
    )

    try:
        runpy.run_path(str(Path(contract_cli.__file__).resolve()), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("Le module __main__ doit terminer via SystemExit")

    current = tmp_path / CURRENT_REPLAY_INPUT_CONTRACT
    assert current.is_file()
    payload = json.loads(current.read_text(encoding="utf-8"))
    assert payload["read_only"] is True
    assert payload["network_used"] is False
    assert payload["raw_data_embedded"] is False

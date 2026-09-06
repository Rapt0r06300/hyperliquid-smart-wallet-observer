from __future__ import annotations

import json
import runpy
import sqlite3
import sys
from pathlib import Path

from hl_observer.datasets.experiment_contract import write_replay_input_contract
from hl_observer.datasets.experiment_plan import CURRENT_EXPERIMENT_PLAN
import hl_observer.ops.dataset_experiment_contract_verify as contract_verify_cli
from hl_observer.ops.dataset_experiment_contract_verify import main


def _prepare_ready_workspace(root: Path) -> Path:
    research = root / "runtime" / "research_lab" / "episodes.jsonl"
    research.parent.mkdir(parents=True, exist_ok=True)
    research.write_text('{"ts_ms":1500,"family":"copy_vault","coin":"BTC"}\n', encoding="utf-8")

    database = root / "data" / "hl_observer.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE fills ("
            "id INTEGER PRIMARY KEY, wallet_address TEXT, coin TEXT, exchange_ts INTEGER, "
            "side TEXT, price REAL, size REAL, closed_pnl REAL, fee REAL, raw_json TEXT)"
        )
        connection.commit()
    finally:
        connection.close()

    plan = {
        "schema": "hypersmart.dataset_experiment_plan.v1",
        "status": "READY",
        "experiment_digest": "a" * 64,
        "criteria": {
            "start_ms": 1000,
            "end_ms": 2000,
            "family": "copy_vault",
            "coin": "BTC",
            "wallet": None,
            "metric": None,
            "require_complete_research": False,
            "include_unknown_time": False,
        },
        "provenance": {
            "status": "READY",
            "source_release_id": 371149058,
            "source_repository": "Rapt0r06300/hypersmart-datasets",
            "suite": "economic-full",
            "selection_digest": "b" * 64,
        },
        "research_lab": {
            "status": "READY",
            "files": [
                {
                    "relative_path": "runtime/research_lab/episodes.jsonl",
                    "source_size": research.stat().st_size,
                    "timestamp_min_ms": 1000,
                    "timestamp_max_ms": 2000,
                    "complete": True,
                    "selection_uncertain": False,
                }
            ],
        },
        "sqlite": {
            "status": "READY",
            "selected": [
                {
                    "database": "data/hl_observer.sqlite3",
                    "table": "fills",
                    "safe_columns": ["wallet_address", "coin", "exchange_ts", "closed_pnl"],
                    "filters": {
                        "start_ms": 1000,
                        "end_ms": 2000,
                        "coin": "BTC",
                        "wallet": None,
                        "family": None,
                    },
                    "family_mode": "IMPLICIT_COPY_SOURCE",
                    "read_only": True,
                }
            ],
        },
    }
    current = root / CURRENT_EXPERIMENT_PLAN
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(json.dumps(plan), encoding="utf-8")
    write_replay_input_contract(root)
    return research


def test_cli_verification_retourne_zero_quand_le_contrat_est_ready(tmp_path: Path, capsys) -> None:
    _prepare_ready_workspace(tmp_path)

    rc = main(["--root", str(tmp_path)])
    output = capsys.readouterr().out

    assert rc == 0
    assert '"status": "READY"' in output
    assert '"row_data_read": false' in output
    assert '"network_used": false' in output


def test_cli_verification_retourne_quatre_si_une_source_a_change(tmp_path: Path, capsys) -> None:
    research = _prepare_ready_workspace(tmp_path)
    research.write_text(research.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    rc = main(["--root", str(tmp_path)])
    output = capsys.readouterr().out

    assert rc == 4
    assert '"status": "NO_GO"' in output
    assert "FILE_SIZE_MISMATCH" in output


def test_cli_verification_retourne_deux_si_le_workspace_est_absent(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "absent"

    rc = main(["--root", str(missing)])
    output = capsys.readouterr().out

    assert rc == 2
    assert "DATASET_CONTRACT_VERIFY_NO_GO" in output


def test_module_entrypoint_verifie_un_contrat_ready(tmp_path: Path, monkeypatch) -> None:
    _prepare_ready_workspace(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["dataset_experiment_contract_verify", "--root", str(tmp_path)],
    )

    try:
        runpy.run_path(str(Path(contract_verify_cli.__file__).resolve()), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("Le module __main__ doit terminer via SystemExit")

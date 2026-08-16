from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hl_observer.datasets.experiment_contract import (
    CURRENT_REPLAY_INPUT_CONTRACT,
    write_replay_input_contract,
)
from hl_observer.datasets.experiment_contract_verifier import (
    CURRENT_CONTRACT_VERIFICATION,
    verify_replay_input_contract,
    write_contract_verification,
)
from hl_observer.datasets.experiment_plan import CURRENT_EXPERIMENT_PLAN


def _workspace(root: Path) -> tuple[Path, Path]:
    research = root / "runtime" / "research_lab" / "episodes.jsonl"
    research.parent.mkdir(parents=True, exist_ok=True)
    research.write_bytes(b"x" * 123)

    database = root / "data" / "hl_observer.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE fills ("
            "id INTEGER PRIMARY KEY, wallet_address TEXT, coin TEXT, exchange_ts INTEGER, "
            "side TEXT, price REAL, size REAL, closed_pnl REAL, fee REAL, raw_json TEXT)"
        )
        connection.execute(
            "INSERT INTO fills (wallet_address, coin, exchange_ts, closed_pnl, raw_json) "
            "VALUES ('0xabc', 'BTC', 1500, 4.0, 'SECRET_ROW_NOT_FOR_VERIFIER')"
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
            "wallet": "0xabc",
            "metric": None,
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
                        "wallet": "0xabc",
                        "family": None,
                    },
                    "family_mode": "IMPLICIT_COPY_SOURCE",
                    "read_only": True,
                }
            ],
        },
    }
    plan_path = root / CURRENT_EXPERIMENT_PLAN
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    write_replay_input_contract(root)
    return research, database


def test_verificateur_accepte_un_contrat_intact_sans_lire_les_lignes(tmp_path: Path) -> None:
    _workspace(tmp_path)

    payload = verify_replay_input_contract(tmp_path)

    assert payload["status"] == "READY"
    assert payload["contract_digest_ok"] is True
    assert payload["experiment_link_ok"] is True
    assert payload["source_count_ok"] is True
    assert payload["declared_source_count"] == 2
    assert payload["verified_source_count"] == 2
    assert payload["row_data_read"] is False
    assert payload["read_only"] is True
    assert payload["network_used"] is False
    assert "SECRET_ROW_NOT_FOR_VERIFIER" not in json.dumps(payload)


def test_verificateur_detecte_un_contrat_modifie_apres_signature(tmp_path: Path) -> None:
    _workspace(tmp_path)
    path = tmp_path / CURRENT_REPLAY_INPUT_CONTRACT
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["criteria"]["coin"] = "ETH"
    path.write_text(json.dumps(payload), encoding="utf-8")

    verification = verify_replay_input_contract(tmp_path)

    assert verification["status"] == "NO_GO"
    assert verification["contract_digest_ok"] is False
    assert "CONTRACT_DIGEST_MISMATCH" in verification["errors"]


def test_verificateur_detecte_un_fichier_research_supprime(tmp_path: Path) -> None:
    research, _ = _workspace(tmp_path)
    research.unlink()

    verification = verify_replay_input_contract(tmp_path)

    assert verification["status"] == "NO_GO"
    assert any("FILE_MISSING" in error for error in verification["errors"])


def test_verificateur_detecte_une_taille_research_modifiee(tmp_path: Path) -> None:
    research, _ = _workspace(tmp_path)
    research.write_bytes(b"y" * 124)

    verification = verify_replay_input_contract(tmp_path)

    assert verification["status"] == "NO_GO"
    assert any("FILE_SIZE_MISMATCH" in error for error in verification["errors"])


def test_verificateur_detecte_une_colonne_sqlite_disparue(tmp_path: Path) -> None:
    _, database = _workspace(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute("ALTER TABLE fills RENAME TO fills_old")
        connection.execute(
            "CREATE TABLE fills (id INTEGER PRIMARY KEY, wallet_address TEXT, coin TEXT, exchange_ts INTEGER)"
        )
        connection.commit()
    finally:
        connection.close()

    verification = verify_replay_input_contract(tmp_path)

    assert verification["status"] == "NO_GO"
    assert any("CONTRACT_COLUMN_MISSING" in error for error in verification["errors"])


def test_verificateur_detecte_un_plan_courant_different(tmp_path: Path) -> None:
    _workspace(tmp_path)
    plan_path = tmp_path / CURRENT_EXPERIMENT_PLAN
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["experiment_digest"] = "c" * 64
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    verification = verify_replay_input_contract(tmp_path)

    assert verification["status"] == "NO_GO"
    assert verification["experiment_link_ok"] is False
    assert "EXPERIMENT_DIGEST_MISMATCH" in verification["errors"]


def test_verification_ecrit_un_rapport_courant(tmp_path: Path) -> None:
    _workspace(tmp_path)

    json_path, md_path, payload = write_contract_verification(tmp_path)

    assert payload["status"] == "READY"
    assert json_path == tmp_path / CURRENT_CONTRACT_VERIFICATION
    assert json_path.is_file()
    assert md_path.is_file()
    assert "Vérification du contrat de replay ciblé" in md_path.read_text(encoding="utf-8")

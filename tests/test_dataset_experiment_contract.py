from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from hl_observer.datasets.experiment_contract import (
    CURRENT_REPLAY_INPUT_CONTRACT,
    build_replay_input_contract,
    load_current_experiment_plan,
    write_replay_input_contract,
)
from hl_observer.datasets.experiment_plan import CURRENT_EXPERIMENT_PLAN


def _ready_plan() -> dict[str, object]:
    return {
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
                    "source_size": 123,
                    "timestamp_min_ms": 1000,
                    "timestamp_max_ms": 2000,
                    "complete": True,
                    "selection_uncertain": False,
                    "family_counts": {"copy_vault": 10},
                    "secret_payload": "NE_DOIT_PAS_ETRE_COPIE",
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
                    "raw_json": "NE_DOIT_PAS_ETRE_COPIE",
                }
            ],
        },
    }


def test_contrat_replay_ne_copie_ni_evenement_brut_ni_sql_libre() -> None:
    contract = build_replay_input_contract(_ready_plan())

    assert contract["schema"] == "hypersmart.replay_input_contract.v2"
    assert contract["source_count"] == 2
    assert contract["research_source_count"] == 1
    assert contract["sqlite_source_count"] == 1
    assert contract["paths_relative_to_workspace"] is True
    assert contract["read_only"] is True
    assert contract["network_used"] is False
    assert contract["raw_data_embedded"] is False
    assert contract["sql_strings_embedded"] is False
    rendered = json.dumps(contract, ensure_ascii=False)
    assert "NE_DOIT_PAS_ETRE_COPIE" not in rendered
    assert "family_counts" not in rendered
    assert "raw_json" not in rendered
    assert contract["sqlite_sources"][0]["filters"]["wallet"] == "0xabc"


def test_contrat_replay_est_reproductible(tmp_path: Path) -> None:
    current = tmp_path / CURRENT_EXPERIMENT_PLAN
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(json.dumps(_ready_plan()), encoding="utf-8")

    first_json, first_md, first = write_replay_input_contract(tmp_path)
    second_json, second_md, second = write_replay_input_contract(tmp_path)

    assert first["contract_digest"] == second["contract_digest"]
    assert first_json == second_json
    assert first_md == second_md
    assert (tmp_path / CURRENT_REPLAY_INPUT_CONTRACT).is_file()
    markdown = first_md.read_text(encoding="utf-8")
    assert "Contrat d'entrée du replay ciblé" in markdown
    assert "chemins sont relatifs au workspace" in markdown


def test_contrat_refuse_un_plan_non_ready() -> None:
    plan = _ready_plan()
    plan["status"] = "NO_MATCH"
    with pytest.raises(ValueError, match="READY"):
        build_replay_input_contract(plan)


def test_contrat_refuse_un_ready_sans_aucune_source() -> None:
    plan = _ready_plan()
    plan["research_lab"] = {"status": "NO_MATCH", "files": []}
    plan["sqlite"] = {"status": "NO_MATCH", "selected": []}
    with pytest.raises(ValueError, match="aucune source"):
        build_replay_input_contract(plan)


@pytest.mark.parametrize(
    "dangerous_path",
    [
        "../secret.jsonl",
        "runtime/research_lab/../../secret.jsonl",
        "/tmp/secret.jsonl",
        "C:\\Users\\flo\\secret.jsonl",
    ],
)
def test_contrat_refuse_un_chemin_research_hors_workspace(dangerous_path: str) -> None:
    plan = copy.deepcopy(_ready_plan())
    plan["research_lab"]["files"][0]["relative_path"] = dangerous_path
    with pytest.raises(ValueError, match="Chemin Research Lab"):
        build_replay_input_contract(plan)


@pytest.mark.parametrize(
    "dangerous_path",
    [
        "../hl_observer.sqlite3",
        "data/../../hl_observer.sqlite3",
        "/tmp/hl_observer.sqlite3",
        "D:\\data\\hl_observer.sqlite3",
    ],
)
def test_contrat_refuse_un_chemin_sqlite_hors_workspace(dangerous_path: str) -> None:
    plan = copy.deepcopy(_ready_plan())
    plan["sqlite"]["selected"][0]["database"] = dangerous_path
    with pytest.raises(ValueError, match="Chemin SQLite"):
        build_replay_input_contract(plan)


def test_contrat_refuse_une_table_sqlite_hors_allowlist() -> None:
    plan = copy.deepcopy(_ready_plan())
    plan["sqlite"]["selected"][0]["table"] = "raw_events"
    with pytest.raises(ValueError, match="Table SQLite non autorisée"):
        build_replay_input_contract(plan)


def test_contrat_refuse_une_colonne_brute_injectee_dans_la_vue_sqlite() -> None:
    plan = copy.deepcopy(_ready_plan())
    plan["sqlite"]["selected"][0]["safe_columns"].append("raw_json")
    with pytest.raises(ValueError, match="Colonnes SQLite non autorisées"):
        build_replay_input_contract(plan)


def test_contrat_ignore_les_criteres_inconnus_du_plan() -> None:
    plan = copy.deepcopy(_ready_plan())
    plan["criteria"]["commande_secrete"] = "DELETE EVERYTHING"
    contract = build_replay_input_contract(plan)
    assert "commande_secrete" not in contract["criteria"]
    assert "DELETE EVERYTHING" not in json.dumps(contract)


def test_loader_refuse_si_plan_courant_absent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dataset_experiment_plan"):
        load_current_experiment_plan(tmp_path)

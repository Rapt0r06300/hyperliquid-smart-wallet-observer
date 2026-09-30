from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hl_observer.datasets.experiment_contract import write_replay_input_contract
from hl_observer.datasets.experiment_contract_verifier import write_contract_verification
from hl_observer.datasets.experiment_plan import write_experiment_plan
from hl_observer.datasets.research_lab_stream import REPORT_JSON


def _prepare_workspace(root: Path) -> Path:
    provenance = root / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(
        json.dumps(
            {
                "source_release_id": 371149058,
                "source_repository": "Rapt0r06300/hypersmart-datasets",
                "suite": "economic-full",
                "selection_digest": "a" * 64,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )

    research = root / "runtime" / "research_lab" / "copy_btc.jsonl"
    research.parent.mkdir(parents=True, exist_ok=True)
    research.write_text(
        json.dumps(
            {
                "ts_ms": 1500,
                "family": "copy_vault",
                "coin": "BTC",
                "net_pnl_usd": 1.25,
                "secret_payload": "NE_DOIT_JAMAIS_ETRE_COPIE",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    profile = {
        "schema": "hypersmart.research_lab_stream_profile.v2",
        "root": str(root),
        "files": [
            {
                "relative_path": "runtime/research_lab/copy_btc.jsonl",
                "source_size": research.stat().st_size,
                "timestamp_min_ms": 1000,
                "timestamp_max_ms": 2000,
                "complete": True,
                "family_counts": {"copy_vault": 1},
                "coin_counts": {"BTC": 1},
                "metrics": {"net_pnl_usd": {"count": 1}},
            }
        ],
    }
    report = root / REPORT_JSON
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(profile), encoding="utf-8")

    database = root / "data" / "hl_observer.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE paper_trades ("
            "id INTEGER PRIMARY KEY, family TEXT, coin TEXT, status TEXT, notional_usd REAL, "
            "entry_price REAL, exit_price REAL, gross_pnl_usd REAL, net_pnl_usd REAL, "
            "fees_usd REAL, spread_cost_usd REAL, slippage_cost_usd REAL, latency_cost_usd REAL, "
            "opened_at_ms INTEGER, closed_at_ms INTEGER, created_at TEXT)"
        )
        connection.execute(
            "INSERT INTO paper_trades VALUES "
            "(1, 'copy_vault', 'BTC', 'CLOSED', 50, 100, 102, 1.5, 1.1, 0.1, 0.1, 0.1, 0.1, 1500, 1600, 'x')"
        )
        connection.commit()
    finally:
        connection.close()
    return research


def test_pipeline_experience_va_du_plan_a_la_verification_sans_copier_les_donnees(tmp_path: Path) -> None:
    _prepare_workspace(tmp_path)

    _, _, plan = write_experiment_plan(
        tmp_path,
        start_ms=900,
        end_ms=2100,
        family="copy_vault",
        coin="BTC",
        metric="net_pnl_usd",
    )
    assert plan["status"] == "READY"
    assert plan["ready_source_count"] >= 2

    _, _, contract = write_replay_input_contract(tmp_path)
    assert contract["source_count"] >= 2
    assert contract["read_only"] is True
    assert contract["network_used"] is False
    assert contract["real_execution"] is False

    _, _, verification = write_contract_verification(tmp_path)
    assert verification["status"] == "READY"
    assert verification["contract_digest_ok"] is True
    assert verification["experiment_link_ok"] is True
    assert verification["declared_source_count"] == verification["verified_source_count"]
    assert verification["row_data_read"] is False
    assert verification["network_used"] is False
    assert verification["real_execution"] is False

    reports = root_reports = tmp_path / "runtime" / "reports" / "datasets"
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in root_reports.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md"}
    )
    assert "NE_DOIT_JAMAIS_ETRE_COPIE" not in combined


def test_pipeline_verification_devient_no_go_si_la_source_change_apres_le_contrat(tmp_path: Path) -> None:
    research = _prepare_workspace(tmp_path)

    write_experiment_plan(
        tmp_path,
        start_ms=900,
        end_ms=2100,
        family="copy_vault",
        coin="BTC",
        metric="net_pnl_usd",
    )
    write_replay_input_contract(tmp_path)

    research.write_text(research.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    _, _, verification = write_contract_verification(tmp_path)

    assert verification["status"] == "NO_GO"
    assert any("FILE_SIZE_MISMATCH" in error for error in verification["errors"])

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hl_observer.datasets.experiment_plan import (
    CURRENT_EXPERIMENT_PLAN,
    build_experiment_plan,
    write_experiment_plan,
)
from hl_observer.datasets.research_lab_stream import REPORT_JSON


def _prepare_workspace(root: Path) -> None:
    provenance = root / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(
        json.dumps(
            {
                "source_release_id": 371149058,
                "source_repository": "Rapt0r06300/hypersmart-datasets",
                "suite": "economic-full",
                "selection_digest": "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    profile = {
        "schema": "hypersmart.research_lab_stream_profile.v2",
        "root": str(root),
        "files": [
            {
                "relative_path": "runtime/research_lab/copy_btc.jsonl",
                "source_size": 100,
                "timestamp_min_ms": 1_000,
                "timestamp_max_ms": 2_000,
                "complete": True,
                "family_counts": {"copy_vault": 20},
                "coin_counts": {"BTC": 20},
                "metrics": {"net_pnl_usd": {"count": 20}},
            },
            {
                "relative_path": "runtime/research_lab/lead_eth.jsonl",
                "source_size": 200,
                "timestamp_min_ms": 1_000,
                "timestamp_max_ms": 2_000,
                "complete": True,
                "family_counts": {"lead_lag": 30},
                "coin_counts": {"ETH": 30},
                "metrics": {"net_pnl_usd": {"count": 30}},
            },
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
            "CREATE TABLE fills ("
            "id INTEGER PRIMARY KEY, wallet_address TEXT, coin TEXT, exchange_ts INTEGER, "
            "side TEXT, price REAL, size REAL, closed_pnl REAL, fee REAL, raw_json TEXT)"
        )
        connection.execute(
            "INSERT INTO fills VALUES (1, '0xabc', 'BTC', 1500, 'B', 100.0, 1.0, 2.0, 0.1, 'SECRET')"
        )
        connection.execute(
            "CREATE TABLE paper_trades ("
            "id INTEGER PRIMARY KEY, family TEXT, coin TEXT, status TEXT, notional_usd REAL, "
            "entry_price REAL, exit_price REAL, gross_pnl_usd REAL, net_pnl_usd REAL, "
            "fees_usd REAL, spread_cost_usd REAL, slippage_cost_usd REAL, latency_cost_usd REAL, "
            "opened_at_ms INTEGER, closed_at_ms INTEGER, created_at TEXT)"
        )
        connection.execute(
            "INSERT INTO paper_trades VALUES "
            "(1, 'copy_vault', 'BTC', 'CLOSED', 50, 100, 102, 1.0, 0.7, 0.1, 0.05, 0.05, 0.1, 1500, 1600, 'x')"
        )
        connection.commit()
    finally:
        connection.close()


def test_plan_combine_research_sqlite_et_provenance_sans_copier_les_donnees(tmp_path: Path) -> None:
    _prepare_workspace(tmp_path)

    plan = build_experiment_plan(
        tmp_path,
        start_ms=900,
        end_ms=2_100,
        family="copy_vault",
        coin="btc",
        metric="net_pnl_usd",
    )

    assert plan["status"] == "READY"
    assert plan["provenance"]["source_release_id"] == 371149058
    assert plan["criteria"]["coin"] == "BTC"
    assert plan["research_lab"]["selected_file_count"] == 1
    assert plan["research_lab"]["files"][0]["relative_path"].endswith("copy_btc.jsonl")
    selected = plan["sqlite"]["selected"]
    assert any(item["table"] == "paper_trades" for item in selected)
    assert all("raw_json" not in item["safe_columns"] for item in selected)
    assert plan["read_only"] is True
    assert plan["network_used"] is False
    assert plan["raw_data_copied"] is False
    assert plan["real_execution"] is False


def test_plan_wallet_copy_vault_reutilise_fills_comme_source_implicite(tmp_path: Path) -> None:
    _prepare_workspace(tmp_path)

    plan = build_experiment_plan(
        tmp_path,
        start_ms=900,
        end_ms=2_100,
        family="copy_vault",
        coin="BTC",
        wallet="0xabc",
    )

    fills = [item for item in plan["sqlite"]["selected"] if item["table"] == "fills"]
    assert len(fills) == 1
    assert fills[0]["family_mode"] == "IMPLICIT_COPY_SOURCE"
    assert fills[0]["filters"]["wallet"] == "0xabc"
    assert fills[0]["filters"]["coin"] == "BTC"
    rejected_paper = [item for item in plan["sqlite"]["rejected"] if item["table"] == "paper_trades"]
    assert any("WALLET_FILTER_UNSUPPORTED" in item["reasons"] for item in rejected_paper)


def test_plan_est_reproductible_et_ecrit_un_pointeur_courant(tmp_path: Path) -> None:
    _prepare_workspace(tmp_path)
    kwargs = {
        "start_ms": 900,
        "end_ms": 2_100,
        "family": "copy_vault",
        "coin": "BTC",
        "metric": "net_pnl_usd",
    }

    first_json, first_md, first = write_experiment_plan(tmp_path, **kwargs)
    second_json, second_md, second = write_experiment_plan(tmp_path, **kwargs)

    assert first["experiment_digest"] == second["experiment_digest"]
    assert first_json == second_json
    assert first_md == second_md
    assert (tmp_path / CURRENT_EXPERIMENT_PLAN).is_file()
    assert "Plan d'expérience FULL/COLD" in first_md.read_text(encoding="utf-8")


def test_plan_refuse_une_periode_inversee(tmp_path: Path) -> None:
    _prepare_workspace(tmp_path)
    try:
        build_experiment_plan(tmp_path, start_ms=2_000, end_ms=1_000)
    except ValueError as exc:
        assert "start_ms" in str(exc)
    else:
        raise AssertionError("Une période inversée doit être refusée")

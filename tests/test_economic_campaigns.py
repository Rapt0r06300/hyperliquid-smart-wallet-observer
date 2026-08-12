from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.simulation.economic_campaigns import (
    build_copy_campaign,
    build_cross_campaign,
    dataset_provenance,
    freeze_parameters,
    render_campaign_report,
)


def test_dataset_provenance_names_partial_hash_honestly(tmp_path: Path) -> None:
    data = tmp_path / "events.jsonl"
    data.write_text('{"ts":1}\n', encoding="utf-8")

    result = dataset_provenance(tmp_path, ("events.jsonl", "missing.jsonl"))

    assert len(result["dataset_fingerprint"]) == 64
    assert result["files"][0]["fingerprint_method"] == "FULL_SHA256"
    assert result["files"][1] == {"path": "missing.jsonl", "exists": False}


def test_parameter_freeze_is_physical_and_immutable(tmp_path: Path) -> None:
    datasets = {"dataset_fingerprint": "d" * 64, "files": []}
    first = freeze_parameters(
        tmp_path,
        "copy_vault",
        {"threshold": 0.1},
        datasets,
        campaign_id="fixed",
        frozen_at_ms=123,
    )
    target = tmp_path / first["path"]

    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8"))["frozen_at_ms"] == 123
    assert freeze_parameters(
        tmp_path,
        "copy_vault",
        {"threshold": 0.1},
        datasets,
        campaign_id="fixed",
        frozen_at_ms=123,
    ) == first
    with pytest.raises(RuntimeError, match="immutable freeze collision"):
        freeze_parameters(
            tmp_path,
            "copy_vault",
            {"threshold": 0.2},
            datasets,
            campaign_id="fixed",
            frozen_at_ms=123,
        )


def test_copy_campaign_never_promotes_without_measured_costs_and_forward() -> None:
    report = {
        "n_entrees_alpha": 50,
        "source_prix": "candles_5m",
        "mesure": {
            "statut": "VALIDATION",
            "decision": "SCALE",
            "oos": {"net_bps": 8.0, "placebo_bps": 1.0, "edge_vs_placebo_bps": 7.0},
        },
        "simulation_paper_oos": {
            "positions_ouvertes": 10,
            "positions_fermees": 10,
            "pnl_brut_realise_usd": 5.0,
            "fees_usd": None,
            "spread_usd": None,
            "slippage_usd": None,
            "latency_usd": None,
            "pnl_net_usd": 4.5,
            "roi_cumulatif_pct": 0.45,
            "drawdown_usd": 0.5,
            "winrate_pct": 60.0,
            "profit_factor": 1.5,
            "LIQUIDATABLE_NET": False,
            "trade_ids_count": 10,
            "trade_ids_sha256": "a" * 64,
            "duplicate_events_rejected": 2,
        },
    }
    campaign = build_copy_campaign(report, freeze=None, datasets={"files": []})

    assert campaign["net_pnl_usd"] == 4.5
    assert campaign["objective_status"] == "NON_ATTEINT"
    assert campaign["forward"] is None
    assert campaign["fees_usd"] is None
    assert "FORWARD_POST_FREEZE_PROOF_MISSING" in campaign["objective_reasons"]


def test_cross_campaign_keeps_unmeasured_slippage_and_two_leg_proof(tmp_path: Path) -> None:
    datasets = {"dataset_fingerprint": "d" * 64, "files": []}
    freeze = freeze_parameters(
        tmp_path,
        "cross_venue_dislocation_v2",
        {"threshold": 15},
        datasets,
        campaign_id="cross",
        frozen_at_ms=1,
    )
    report = {
        "verdict_realiste_16bps": {
            "verdict": "KILL",
            "n_trades": 2,
            "positions_ouvertes": 2,
            "positions_fermees": 2,
            "gross_pnl_usd": 1.0,
            "fees_usd": 0.2,
            "spread_cost_usd": 0.1,
            "slippage_cost_usd": None,
            "latency_cost_usd": 0.1,
            "net_total_usd": 0.6,
            "roi_pct": 0.06,
            "max_drawdown_usd": 0.2,
            "hit_rate": 0.5,
            "profit_factor": 1.0,
            "LIQUIDATABLE_NET": False,
            "all_positions_two_leg_closed": True,
            "duplicate_trade_ids": 0,
            "trade_ids_count": 2,
            "trade_ids_sha256": "b" * 64,
        },
        "trades": [
            {"ts_detect": 10, "ts_out": 20},
            {"ts_detect": 30, "ts_out": 40},
        ],
    }
    campaign = build_cross_campaign(report, freeze=freeze, datasets=datasets)

    assert campaign["all_positions_two_leg_closed"] is True
    assert campaign["slippage_cost_usd"] is None
    assert campaign["liquidatable_net"] is False
    assert campaign["objective_status"] == "NON_ATTEINT"


def test_campaign_json_has_no_case_insensitive_duplicate_keys(tmp_path: Path) -> None:
    campaign = build_copy_campaign({}, freeze=None, datasets={"files": []})
    lowered = [key.lower() for key in campaign]

    assert len(lowered) == len(set(lowered))
    assert "liquidatable_net" in campaign
    assert "LIQUIDATABLE_NET" not in campaign


def test_markdown_starts_each_family_with_exact_objective_verdict() -> None:
    rows = [
        {"family": "copy_vault", "objective_status": "NON_ATTEINT", "objective_reasons": []},
        {"family": "lead_lag", "objective_status": "NON_ATTEINT", "objective_reasons": []},
        {
            "family": "cross_venue_dislocation_v2",
            "objective_status": "NON_ATTEINT",
            "objective_reasons": [],
        },
    ]
    report = render_campaign_report(rows)

    assert "Copy-Vault - OBJECTIF +4 USD : NON_ATTEINT" in report
    assert "Lead-Lag - OBJECTIF +4 USD : NON_ATTEINT" in report
    assert "Cross-Venue Dislocation v2 - OBJECTIF +4 USD : NON_ATTEINT" in report
    assert "Carry OFF" in report

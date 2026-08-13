from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.simulation.economic_campaigns import (
    build_copy_campaign,
    build_cross_campaign,
    build_lead_lag_campaign,
    dataset_provenance,
    freeze_or_reuse_parameters,
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


def test_freeze_identique_est_reutilise_sans_deplacer_frontiere_forward(tmp_path: Path) -> None:
    datasets = {"dataset_fingerprint": "d" * 64, "files": []}
    original = freeze_parameters(
        tmp_path,
        "lead_lag",
        {"threshold": 7.0},
        datasets,
        campaign_id="physical-freeze",
        frozen_at_ms=123,
    )

    reused = freeze_or_reuse_parameters(
        tmp_path,
        "lead_lag",
        {"threshold": 7.0},
        {"dataset_fingerprint": "new-data", "files": []},
    )

    assert reused == original
    assert reused["frozen_at_ms"] == 123
    assert len(list((tmp_path / "runtime/reports/economic_campaigns/freezes/lead_lag").glob("*.json"))) == 1


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


def test_executable_copy_campaign_maps_only_closed_liquidatable_evidence(tmp_path: Path) -> None:
    datasets = {"dataset_fingerprint": "d" * 64, "files": []}
    freeze = freeze_parameters(
        tmp_path,
        "copy_vault",
        {"calibration_protocol": "copy_vault_executable_walk_forward_v1"},
        datasets,
        campaign_id="copy-executable",
        frozen_at_ms=10,
    )
    report = {
        "schema_version": "hypersmart.copy_vault_executable_campaign.v1",
        "metaorder_audit": {"metaorders": 3},
        "summary": {
            "positions_ouvertes": 2,
            "positions_fermees": 2,
            "gross_pnl_usd": 5.0,
            "fees_usd": 0.2,
            "spread_cost_usd": 0.3,
            "slippage_cost_usd": 0.0,
            "latency_cost_usd": 0.1,
            "net_pnl_usd": 4.4,
            "roi_pct": 0.44,
            "max_drawdown_usd": 0.1,
            "hit_rate": 1.0,
            "profit_factor": float("inf"),
            "LIQUIDATABLE_NET": True,
            "duplicate_trade_ids": 0,
            "trade_ids_count": 2,
            "trade_ids_sha256": "c" * 64,
        },
        "temporal_evidence": {
            "oos": {"net_pnl_usd": 1.0, "sample_count": 1, "no_lookahead": True},
            "forward": {"net_pnl_usd": 1.0, "sample_count": 1, "post_freeze": True},
            "placebos": {"beaten": True},
        },
    }

    campaign = build_copy_campaign(report, freeze=freeze, datasets=datasets)

    assert campaign["net_pnl_usd"] == 4.4
    assert campaign["liquidatable_net"] is True
    assert campaign["objective_status"] == "ATTEINT"


def test_executable_copy_campaign_zero_closed_is_non_mesurable() -> None:
    report = {
        "schema_version": "hypersmart.copy_vault_executable_campaign.v1",
        "metaorder_audit": {"metaorders": 21},
        "summary": {
            "positions_ouvertes": 0,
            "positions_fermees": 0,
            "gross_pnl_usd": 0.0,
            "fees_usd": 0.0,
            "spread_cost_usd": 0.0,
            "slippage_cost_usd": 0.0,
            "latency_cost_usd": 0.0,
            "net_pnl_usd": 0.0,
            "LIQUIDATABLE_NET": False,
            "duplicate_trade_ids": 0,
            "trade_ids_count": 0,
            "trade_ids_sha256": "e" * 64,
        },
    }
    campaign = build_copy_campaign(report, freeze=None, datasets={"files": []})

    assert campaign["net_pnl_usd"] is None
    assert campaign["gross_pnl_usd"] is None
    assert "UNMEASURED:net_pnl_usd" in campaign["objective_reasons"]


def test_executable_lead_lag_campaign_maps_closed_ledger_and_temporal_proof(
    tmp_path: Path,
) -> None:
    datasets = {"dataset_fingerprint": "d" * 64, "files": []}
    freeze = freeze_parameters(
        tmp_path,
        "lead_lag",
        {"execution_model": "causal_marketable_top_v3"},
        datasets,
        campaign_id="lead-executable",
        frozen_at_ms=10,
    )
    report = {
        "statut": "PROMETTEUR",
        "chocs_test": 4,
        "executable_campaign": {
            "execution_model": "causal_marketable_top_v3",
            "diagnostics": {"candidate_observations": 4, "missing_top_sizes": 0},
            "summary": {
                "positions_ouvertes": 4,
                "positions_fermees": 4,
                "gross_pnl_usd": 5.0,
                "fees_usd": 0.2,
                "spread_cost_usd": 0.2,
                "slippage_cost_usd": 0.0,
                "latency_cost_usd": 0.1,
                "net_pnl_usd": 4.5,
                "roi_pct": 0.45,
                "max_drawdown_usd": 0.1,
                "hit_rate": 0.75,
                "profit_factor": 3.0,
                "LIQUIDATABLE_NET": True,
                "duplicate_trade_ids": 0,
                "trade_ids_count": 4,
                "trade_ids_sha256": "f" * 64,
            },
            "temporal_evidence": {
                "oos": {"net_pnl_usd": 1.0, "sample_count": 1, "no_lookahead": True},
                "forward": {"net_pnl_usd": 1.0, "sample_count": 1, "post_freeze": True},
                "placebos": {"beaten": True},
            },
        },
    }

    campaign = build_lead_lag_campaign(report, freeze=freeze, datasets=datasets)

    assert campaign["net_pnl_usd"] == 4.5
    assert campaign["closed_positions"] == 4
    assert campaign["liquidatable_net"] is True
    assert campaign["objective_status"] == "ATTEINT"


def test_lead_lag_without_sized_closed_episodes_remains_unmeasured() -> None:
    report = {
        "statut": "PAS_D_EDGE",
        "executable_campaign": {
            "diagnostics": {"candidate_observations": 20, "missing_top_sizes": 20},
            "summary": {
                "positions_ouvertes": 0,
                "positions_fermees": 0,
                "gross_pnl_usd": 0.0,
                "fees_usd": 0.0,
                "spread_cost_usd": 0.0,
                "slippage_cost_usd": 0.0,
                "latency_cost_usd": 0.0,
                "net_pnl_usd": 0.0,
                "LIQUIDATABLE_NET": False,
                "duplicate_trade_ids": 0,
                "trade_ids_count": 0,
                "trade_ids_sha256": "0" * 64,
            },
        },
    }

    campaign = build_lead_lag_campaign(report, freeze=None, datasets={"files": []})

    assert campaign["source_status"] == "FUTURE_SIZED_BBO_REQUIRED"
    assert campaign["net_pnl_usd"] is None
    assert campaign["objective_status"] == "NON_ATTEINT"
    assert "UNMEASURED:net_pnl_usd" in campaign["objective_reasons"]


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


def test_protocol_freeze_reuses_oldest_boundary_after_dataset_growth(tmp_path: Path) -> None:
    protocol = {"calibration_protocol": "wf-v1", "grid_sha256": "a" * 64}
    old = freeze_parameters(
        tmp_path,
        "cross_venue_dislocation_v2",
        {**protocol, "walk_forward_bounds": {"oos_start_ms": 100}},
        {"dataset_fingerprint": "old"},
        campaign_id="old",
        frozen_at_ms=1000,
    )
    freeze_parameters(
        tmp_path,
        "cross_venue_dislocation_v2",
        {**protocol, "walk_forward_bounds": {"oos_start_ms": 999}},
        {"dataset_fingerprint": "new"},
        campaign_id="new",
        frozen_at_ms=2000,
    )

    from hl_observer.simulation.economic_campaigns import find_oldest_parameter_freeze

    reused = find_oldest_parameter_freeze(
        tmp_path,
        "cross_venue_dislocation_v2",
        required_parameters=protocol,
    )

    assert reused == old
    assert reused["parameters"]["walk_forward_bounds"]["oos_start_ms"] == 100


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

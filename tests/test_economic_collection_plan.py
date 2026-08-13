from __future__ import annotations

import json
from pathlib import Path

from hl_observer.simulation.economic_collection_plan import (
    build_collection_plan,
    write_collection_plan,
)


def _campaign(family: str, **changes):
    row = {
        "family": family,
        "objective_status": "NON_ATTEINT",
        "objective_reasons": ["TARGET_NET_USD_NOT_REACHED"],
        "closed_positions": 0,
        "parameter_freeze": None,
    }
    row.update(changes)
    return row


def _raw_reports():
    return {
        "copy_vault": {
            "schema_version": "hypersmart.copy_vault_executable_campaign.v1",
            "canonical_input_audit": {
                "raw_fills": 100,
                "alpha_entries": 12,
                "missing_or_stale_asof_nav_rejected": 7,
            },
            "metaorder_audit": {"metaorders": 9},
            "book_meta": {"valid_rows": 1000, "coins": 3},
            "calibration": {
                "grid": [
                    {"diagnostics": {"STALE_OR_MISSING_REFERENCE_BOOK": 9}}
                ]
            },
        },
        "lead_lag": {
            "executable_campaign": {
                "schema_version": "hypersmart.lead_lag_executable_campaign.v1",
                "execution_model": "causal_marketable_top_v3",
                "diagnostics": {
                    "candidate_observations": 30,
                    "liquidatable_observations": 0,
                    "missing_top_sizes": 30,
                },
            }
        },
        "cross_venue_dislocation_v2": {
            "schema_version": "hypersmart.cross_venue_campaign.v2",
            "verdict_realiste_16bps": {
                "positions_fermees": 20,
                "net_total_usd": -2.0,
                "profit_factor": 0.5,
                "LIQUIDATABLE_NET": True,
                "all_positions_two_leg_closed": True,
            },
            "temporal_evidence": {
                "oos": {"net_pnl_usd": -0.4, "sample_count": 4},
                "forward": {"net_pnl_usd": None, "sample_count": 0},
                "placebos": {"beaten": False},
            },
        },
    }


def test_plan_distinguishes_future_data_from_killed_hypothesis() -> None:
    campaigns = [
        _campaign("copy_vault"),
        _campaign("lead_lag"),
        _campaign("cross_venue_dislocation_v2", closed_positions=20),
    ]

    plan = build_collection_plan(campaigns, _raw_reports(), now_ms=123)
    by_family = {row["family"]: row for row in plan["families"]}

    assert by_family["copy_vault"]["future_data_required_only"] is True
    assert by_family["lead_lag"]["evidence_state"] == "FUTURE_SIZED_BBO_REQUIRED"
    assert by_family["cross_venue_dislocation_v2"]["evidence_state"] == "HYPOTHESIS_KILLED_OOS"
    assert by_family["cross_venue_dislocation_v2"]["future_data_required_only"] is False
    assert plan["safe_to_claim_future_data_required_only"] is False
    assert plan["goal_complete"] is False
    assert plan["real_execution"] is False


def test_plan_records_exact_collectors_progress_and_freeze() -> None:
    campaigns = [
        _campaign("copy_vault"),
        _campaign(
            "lead_lag",
            parameter_freeze={
                "campaign_id": "lead-freeze",
                "frozen_at_ms": 100,
                "parameters_sha256": "a" * 64,
                "path": "freeze.json",
            },
        ),
        _campaign("cross_venue_dislocation_v2", closed_positions=20),
    ]

    plan = build_collection_plan(
        campaigns,
        _raw_reports(),
        collector_state={"profil": "harvest", "manquants": []},
        now_ms=123,
    )
    lead = next(row for row in plan["families"] if row["family"] == "lead_lag")

    assert "bbo-collector" in plan["required_collectors"]
    assert "vault-collector" in plan["required_collectors"]
    assert lead["freeze"]["campaign_id"] == "lead-freeze"
    assert lead["progress"]["missing_top_sizes"] == 30
    assert plan["collector_state"]["profil"] == "harvest"


def test_write_plan_is_strict_json_and_human_readable(tmp_path: Path) -> None:
    campaigns = [
        _campaign("copy_vault"),
        _campaign("lead_lag"),
        _campaign("cross_venue_dislocation_v2", closed_positions=20),
    ]
    plan = build_collection_plan(campaigns, _raw_reports(), now_ms=123)

    state_path, report_path = write_collection_plan(tmp_path, plan)
    decoded = json.loads(state_path.read_text(encoding="utf-8"))

    assert decoded["generated_at_ms"] == 123
    assert decoded["paper_read_only"] is True
    assert "NaN" not in state_path.read_text(encoding="utf-8")
    assert "Infinity" not in state_path.read_text(encoding="utf-8")
    assert "HYPOTHESIS_KILLED_OOS" in report_path.read_text(encoding="utf-8")

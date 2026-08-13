from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.copy_vault_executable import PROTOCOL_NAME
from hl_observer.collection.copy_vault_checkpoint_tail import COMPANION_PROTOCOL
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
            "causal_protocol_audit": {
                "causal_protocol_metaorders": 9,
                "causal_protocol_book_rows": 1000,
            },
            "calibration": {
                "selection_eligible": False,
                "minimum_train_trades": 8,
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
    assert by_family["cross_venue_dislocation_v2"]["collection_actionable"] is False
    assert "venues-collector" not in plan["required_collectors"]
    # carnet remains useful for Copy-Vault even though Cross itself is killed.
    assert "carnet-collector" in plan["required_collectors"]
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
    copy = next(row for row in plan["families"] if row["family"] == "copy_vault")
    assert "runtime/data/copy_vault_l2_tape.jsonl" in copy["required_artifacts"]
    assert "runtime/data/vault_fills_live.jsonl" in copy["required_artifacts"]
    assert copy["progress"]["causal_protocol_metaorders"] == 9
    assert copy["progress"]["causal_protocol_book_rows"] == 1000
    assert copy["progress"]["stale_or_missing_book_rejections_across_grid"] == 9
    assert copy["progress"]["book_rejections_across_grid"]["STALE_OR_MISSING_REFERENCE_BOOK"] == 9
    assert lead["freeze"]["campaign_id"] == "lead-freeze"
    assert lead["progress"]["missing_top_sizes"] == 30
    assert plan["collector_state"]["profil"] == "harvest"


def test_copy_plan_requires_running_causal_checkpoint_protocol() -> None:
    campaigns = [
        _campaign("copy_vault"),
        _campaign("lead_lag"),
        _campaign("cross_venue_dislocation_v2", closed_positions=20),
    ]
    stale = build_collection_plan(
        campaigns,
        _raw_reports(),
        collector_state={
            "actifs": {"userfills-live": 42},
            "protocols": {},
        },
        now_ms=123,
    )
    copy = next(row for row in stale["families"] if row["family"] == "copy_vault")
    assert copy["evidence_state"] == "CAUSAL_COLLECTOR_PROTOCOL_RESTART_REQUIRED"
    assert copy["running_collector_protocol_ready"] is False
    assert copy["future_data_required_only"] is False
    assert "restart userfills-live" in copy["exact_missing_evidence"][0]

    current = build_collection_plan(
        campaigns,
        _raw_reports(),
        collector_state={
            "actifs": {"userfills-live": 42},
            "protocols": {"userfills-live": PROTOCOL_NAME},
        },
        now_ms=123,
    )
    copy = next(row for row in current["families"] if row["family"] == "copy_vault")
    assert copy["evidence_state"] == "FUTURE_CAUSAL_BOOK_AND_VAULT_DATA_REQUIRED"
    assert copy["running_collector_protocol_ready"] is True
    assert copy["progress"]["active_collector_protocol"] == PROTOCOL_NAME

    companion = build_collection_plan(
        campaigns,
        _raw_reports(),
        collector_state={
            "actifs": {
                "userfills-live": 42,
                "copy-vault-checkpoints": 43,
            },
            "protocols": {
                "copy-vault-checkpoints": COMPANION_PROTOCOL,
            },
        },
        now_ms=123,
    )
    copy = next(row for row in companion["families"] if row["family"] == "copy_vault")
    assert copy["evidence_state"] == "FUTURE_CAUSAL_BOOK_AND_VAULT_DATA_REQUIRED"
    assert copy["running_collector_protocol_ready"] is True
    assert copy["progress"]["active_companion_protocol"] == COMPANION_PROTOCOL
    assert "copy-vault-checkpoints" in copy["required_collectors"]


def test_plan_kills_frozen_lead_lag_negative_oos_and_forward() -> None:
    raw = _raw_reports()
    raw["lead_lag"]["executable_campaign"]["temporal_evidence"] = {
        "oos": {
            "net_pnl_usd": -0.21,
            "sample_count": 9,
            "no_lookahead": True,
        },
        "forward": {
            "net_pnl_usd": -0.60,
            "sample_count": 15,
            "post_freeze": True,
        },
        "placebos": {"beaten": True},
    }
    campaigns = [
        _campaign("copy_vault"),
        _campaign(
            "lead_lag",
            closed_positions=24,
            net_pnl_usd=-0.81,
            profit_factor=0.02,
        ),
        _campaign("cross_venue_dislocation_v2", closed_positions=20),
    ]

    plan = build_collection_plan(campaigns, raw, now_ms=123)
    lead = next(row for row in plan["families"] if row["family"] == "lead_lag")

    assert lead["evidence_state"] == "HYPOTHESIS_KILLED_OOS_FORWARD"
    assert lead["collection_actionable"] is False
    assert lead["future_data_required_only"] is False
    assert lead["methodology_action"] == "KILL_CURRENT_FROZEN_HYPOTHESIS_OR_DECLARE_NEW_MECHANISM"
    assert lead["progress"]["oos_net_pnl_usd"] == -0.21
    assert lead["progress"]["forward_net_pnl_usd"] == -0.60
    assert "bbo-collector" not in plan["required_collectors"]
    assert "allmids-collector" not in plan["required_collectors"]


def test_copy_plan_counts_entry_exit_and_missing_coin_book_rejections() -> None:
    raw = _raw_reports()
    raw["copy_vault"]["calibration"]["grid"] = [
        {
            "summary": {"positions_fermees": 0},
            "diagnostics": {
                "NO_OBSERVED_BOOK_FOR_COIN": 1,
                "STALE_OR_MISSING_ENTRY_BOOK": 2,
                "STALE_OR_MISSING_EXIT_BOOK": 3,
            },
        }
    ]
    campaigns = [
        _campaign("copy_vault", closed_positions=1, net_pnl_usd=0.75),
        _campaign("lead_lag"),
        _campaign("cross_venue_dislocation_v2", closed_positions=20),
    ]

    plan = build_collection_plan(campaigns, raw, now_ms=123)
    copy = next(row for row in plan["families"] if row["family"] == "copy_vault")

    assert copy["evidence_state"] == "FUTURE_CAUSAL_BOOK_AND_VAULT_DATA_REQUIRED"
    assert copy["future_data_required_only"] is True
    assert copy["progress"]["stale_or_missing_book_rejections_across_grid"] == 6
    assert copy["progress"]["book_rejections_across_grid"] == {
        "NO_OBSERVED_BOOK_FOR_COIN": 1,
        "STALE_OR_MISSING_REFERENCE_BOOK": 0,
        "STALE_OR_MISSING_ENTRY_BOOK": 2,
        "STALE_OR_MISSING_EXIT_BOOK": 3,
        "NON_CAUSAL_FORWARD_BOOK": 0,
    }
    assert copy["progress"]["parameters_frozen"] is False


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
    assert "Collecte encore actionnable" in report_path.read_text(encoding="utf-8")

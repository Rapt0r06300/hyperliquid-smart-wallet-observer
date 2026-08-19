from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.cross_venue_certified import (
    FOUR_FILL_CONTRACT_VERSION,
    SOURCE_MODE,
)
from hl_observer.ops.final_economic_certification import (
    certify_campaign,
    certify_workspace,
)
from hl_observer.simulation.economic_objective import evaluate_objective


FAMILIES = ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")


def _segment(*, net: float, hash_char: str, post_freeze: bool = False, no_lookahead: bool = False) -> dict:
    return {
        "sample_count": 1,
        "gross_pnl_usd": net + 0.4,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "net_pnl_usd": net,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 1,
        "trade_ids_sha256": hash_char * 64,
        "post_freeze": post_freeze,
        "no_lookahead": no_lookahead,
    }


def _certified_campaign(family: str) -> dict:
    row = {
        "family": family,
        "starting_capital_usd": 1000.0,
        "paper_read_only": True,
        "real_execution": False,
        "parameters_frozen": True,
        "opened_positions": 2,
        "closed_positions": 2,
        "gross_pnl_usd": 5.0,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "net_pnl_usd": 4.6,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 2,
        "trade_ids_sha256": "a" * 64,
        "oos": _segment(net=2.1, hash_char="b", no_lookahead=True),
        "forward": _segment(net=2.1, hash_char="c", post_freeze=True),
        "placebos": {"beaten": True},
    }
    if family == "copy_vault":
        row["vault_generalization"] = {"sample_count": 20, "net_bps": 1.0}
    if family == "cross_venue_dislocation_v2":
        row["all_positions_two_leg_closed"] = True
        row["period"] = {
            "collection_meta": {
                "source_mode": SOURCE_MODE,
                "certified_snapshots": 2,
                "mapping_verified": True,
                "skew_verified": True,
                "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION,
            }
        }
    row.update(evaluate_objective(row))
    assert row["objective_status"] == "ATTEINT"
    return row


def test_certification_recalcule_la_gate_et_certifie_une_preuve_complete() -> None:
    row = _certified_campaign("lead_lag")
    result = certify_campaign("lead_lag", row)
    assert result["certified"] is True
    assert result["eligible_net_pnl_usd"] >= 4.0
    assert result["liquidatable_net"] is True
    assert result["oos_positive"] is True
    assert result["forward_positive"] is True
    assert result["forward_post_freeze"] is True
    assert result["placebo_beaten"] is True
    assert result["reasons"] == []


def test_certification_refuse_un_statut_atteint_falsifie() -> None:
    row = _certified_campaign("lead_lag")
    row["forward"]["post_freeze"] = False
    row["objective_status"] = "ATTEINT"
    result = certify_campaign("lead_lag", row)
    assert result["certified"] is False
    assert result["status"] == "NO_GO"
    assert "OBJECTIVE_STATUS_DRIFT" in result["reasons"]
    assert "FORWARD_NOT_PROVEN_POST_FREEZE" in result["reasons"]


def test_workspace_exige_les_trois_familles_sans_compensation(tmp_path: Path) -> None:
    campaign_dir = tmp_path / "runtime" / "reports" / "economic_campaigns"
    campaign_dir.mkdir(parents=True)
    for family in FAMILIES:
        row = _certified_campaign(family)
        (campaign_dir / f"{family}.json").write_text(json.dumps(row), encoding="utf-8")

    certified = certify_workspace(tmp_path)
    assert certified["all_families_certified"] is True
    assert certified["cross_family_pnl_compensation_allowed"] is False
    assert all(row["certified"] for row in certified["families"].values())

    weak = _certified_campaign("lead_lag")
    weak["forward"]["net_pnl_usd"] = -10.0
    weak.update(evaluate_objective(weak))
    (campaign_dir / "lead_lag.json").write_text(json.dumps(weak), encoding="utf-8")

    refused = certify_workspace(tmp_path)
    assert refused["all_families_certified"] is False
    assert refused["families"]["lead_lag"]["certified"] is False
    assert refused["families"]["copy_vault"]["certified"] is True
    assert refused["families"]["cross_venue_dislocation_v2"]["certified"] is True

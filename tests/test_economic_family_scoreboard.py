from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.simulation.economic_family_scoreboard import (
    build_scoreboards,
    promotion_verdict,
)
from hl_observer.ui.app import create_ui_app

ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, relative: str, payload: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_scoreboards_keep_families_separate_and_deny_incomplete_evidence(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "runtime/data/copy_edge_rapport_reel.json",
        {"n_entrees_alpha": 3144, "mesure": {"statut": "NEED_MORE_DATA", "n_train": 20, "n_oos": 10}},
    )
    _write(
        tmp_path,
        "runtime/audit/v2_lead_lag/lead_lag_shadow_frozen.json",
        {"frozen_evidence": {"source_status": "NEED_MORE_DATA", "sample_n_by_horizon": {}}},
    )
    _write(
        tmp_path,
        "runtime/data/lead_lag_event_runtime_status.json",
        {"enabled": False, "code": "EVIDENCE_NOT_PROMOTED", "rejected": 0},
    )
    _write(
        tmp_path,
        "docs/audit/CROSS_VENUE_DISLOCATION_FINAL_verdict.json",
        {
            "n_trades": 81,
            "verdict_realiste_16bps": {
                "verdict": "KILL",
                "n_trades": 81,
                "net_total_usd": -0.1366,
                "pf": 0.732,
                "dd_usd": -0.3208,
            },
        },
    )

    result = build_scoreboards(tmp_path)

    assert set(result["families"]) == {
        "copy_vault",
        "lead_lag",
        "cross_venue_dislocation_v2",
    }
    assert result["families"]["copy_vault"]["verdict"] == "MORE_DATA"
    assert result["families"]["lead_lag"]["verdict"] == "MORE_DATA"
    cross = result["families"]["cross_venue_dislocation_v2"]
    assert cross["verdict"] == "KILL"
    assert cross["net_pnl_usd"] == -0.1366
    assert cross["liquidatable_net"] is False
    assert result["disabled_families"] == ["cross_venue_dislocation_v1", "carry"]
    assert result["starting_capital_usd"] == 1000.0
    assert result["real_execution"] is False


def test_promotion_requires_positive_oos_forward_placebo_and_sample() -> None:
    complete = {
        "closed_positions": 30,
        "net_pnl_usd": 1.0,
        "roi_pct": 0.1,
        "max_drawdown_usd": 0.5,
        "hit_rate": 0.6,
        "profit_factor": 1.2,
        "oos": {"net_pnl_usd": 0.2},
        "forward": {"net_pnl_usd": 0.1},
        "placebos": {"beaten": True},
        "liquidatable_net": True,
    }
    assert promotion_verdict(complete) == ("PROMOTE", [])
    incomplete = dict(complete, forward=None)
    assert promotion_verdict(incomplete)[0] == "MORE_DATA"
    negative = dict(complete, net_pnl_usd=-0.01)
    assert promotion_verdict(negative)[0] == "KILL"


def test_strict_campaign_is_preferred_and_never_double_counts_arbitrage(tmp_path: Path) -> None:
    campaign = {
        "family": "cross_venue_dislocation_v2",
        "starting_capital_usd": 1000.0,
        "paper_read_only": True,
        "real_execution": False,
        "parameters_frozen": True,
        "all_positions_two_leg_closed": True,
        "signal_count": 40,
        "opened_positions": 30,
        "closed_positions": 30,
        "gross_pnl_usd": 7.0,
        "fees_usd": 1.0,
        "spread_cost_usd": 0.5,
        "slippage_cost_usd": 0.5,
        "latency_cost_usd": 0.5,
        "net_pnl_usd": 4.5,
        "roi_pct": 0.45,
        "max_drawdown_usd": 0.8,
        "hit_rate": 0.6,
        "profit_factor": 1.4,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 30,
        "trade_ids_sha256": "a" * 64,
        "oos": {"net_pnl_usd": 2.0, "sample_count": 15, "no_lookahead": True},
        "forward": {"net_pnl_usd": 2.5, "sample_count": 15, "post_freeze": True},
        "placebos": {"beaten": True},
    }
    _write(
        tmp_path,
        "runtime/reports/economic_campaigns/cross_venue_dislocation_v2.json",
        campaign,
    )
    _write(
        tmp_path,
        "docs/audit/CROSS_VENUE_DISLOCATION_FINAL_verdict.json",
        {"n_trades": 999, "verdict_realiste_16bps": {"net_total_usd": -99}},
    )

    result = build_scoreboards(tmp_path)
    row = result["families"]["cross_venue_dislocation_v2"]

    assert row["objective_status"] == "ATTEINT"
    assert row["eligible_net_pnl_usd"] == 4.5
    assert row["signal_count"] == 40
    assert "LIQUIDATABLE_NET" not in row
    assert list(result["families"]).count("cross_venue_dislocation_v2") == 1


def test_public_paper_default_uses_the_unique_1000_usd_capital() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "HYPERSMART_PAPER_STARTING_EQUITY=1000.0" in env_example
    assert "HYPERSMART_PAPER_STARTING_EQUITY=10000.0" not in env_example


def test_scoreboards_are_reachable_from_the_read_only_runtime() -> None:
    response = TestClient(create_ui_app(), raise_server_exceptions=True).get(
        "/api/simulation/economic-scoreboards"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_families"] == [
        "copy_vault",
        "lead_lag",
        "cross_venue_dislocation_v2",
    ]
    assert payload["paper_read_only"] is True
    assert payload["real_execution"] is False

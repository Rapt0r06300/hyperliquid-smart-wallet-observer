from __future__ import annotations

import json
from pathlib import Path

from hl_observer.simulation.economic_family_scoreboard import (
    build_scoreboards,
    promotion_verdict,
)

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


def test_public_paper_default_uses_the_unique_1000_usd_capital() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "HYPERSMART_PAPER_STARTING_EQUITY=1000.0" in env_example
    assert "HYPERSMART_PAPER_STARTING_EQUITY=10000.0" not in env_example

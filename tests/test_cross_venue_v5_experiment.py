from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting import cross_venue_v5_experiment as module


def test_evaluate_cross_venue_v5_refresh_writes_detail_and_compacts_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        module,
        "load_preferred_certified_atomic_series",
        lambda root: (
            {"ETH": [(1.0, "ATOMIC_BBO", 100.0, 101.0, 102.0, 103.0)]},
            {"ETH": [(1.0, 500.0)]},
            {
                "source": "runtime/data/cross_venue_atomic_bbo.jsonl",
                "source_mode": "CERTIFIED_ATOMIC_BBO_V1",
                "certified_snapshots": 1,
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "explore_cross_venue_v5_train",
        lambda series, depth, source_mode: {
            "status": "TRAIN_ELIGIBLE_TO_FREEZE",
            "selection_eligible": True,
            "economic_contract": {
                "values": {"cross_venue.paper_notional_usd": 15.0}
            },
            "selected": {
                "statistics": {
                    "sample_count": 12,
                    "distinct_days": 3,
                    "net_pnl_usd": 4.5,
                    "profit_factor": 1.8,
                    "total_lcb_usd": 0.4,
                    "max_drawdown_usd": 0.2,
                    "top_positive_trade_share": 0.2,
                }
            },
            "paper_read_only": True,
            "real_execution": False,
        },
    )

    result = module.evaluate_cross_venue_v5_refresh(
        {"refresh": True},
        context={
            "experiment_id": "cross-v5-test",
            "base_sha": "a" * 40,
            "data_fingerprint": "sha256:test",
            "data_cutoff_utc": "2026-09-10T00:00:00Z",
        },
    )

    assert result["candidate_verdict"] == "FREEZE_CANDIDATE"
    assert result["train_net_pnl_usd"] == 4.5
    assert result["sample_count"] == 12
    assert result["distinct_days"] == 3
    assert result["pf"] == 1.8
    assert result["total_lcb_usd"] == 0.4
    assert result["roi_immobilise_pct"] == 2.5
    assert result["certified_snapshots"] == 1
    detail_path = Path(result["detail_artifact"])
    assert detail_path.exists()
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    assert detail["report"]["selection_eligible"] is True
    assert detail["source_meta"]["certified_snapshots"] == 1
    assert detail["base_sha"] == "a" * 40


def test_evaluate_cross_venue_v5_refresh_uses_diagnostic_when_not_eligible(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        module,
        "load_preferred_certified_atomic_series",
        lambda root: ({}, {}, {"source_mode": "CERTIFIED_ATOMIC_BBO_V1"}),
    )
    monkeypatch.setattr(
        module,
        "explore_cross_venue_v5_train",
        lambda series, depth, source_mode: {
            "status": "NO_ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": False,
            "selected": None,
            "diagnostic_best_train_variant": {
                "statistics": {
                    "sample_count": 7,
                    "distinct_days": 2,
                    "net_pnl_usd": -0.3,
                    "profit_factor": 0.8,
                    "total_lcb_usd": -1.1,
                }
            },
        },
    )

    result = module.evaluate_cross_venue_v5_refresh(
        {"refresh": True}, context={"experiment_id": "cross-v5-test"}
    )

    assert result["candidate_verdict"] == "REJECT"
    assert result["qualification_status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["train_net_pnl_usd"] == -0.3


def test_evaluate_cross_venue_v5_refresh_rejects_nonconstant_parameter() -> None:
    try:
        module.evaluate_cross_venue_v5_refresh(
            {"refresh": False}, context={"experiment_id": "cross-v5-test"}
        )
    except ValueError as exc:
        assert str(exc) == "refresh must be true"
    else:
        raise AssertionError("expected invalid experiment parameters to fail")

from tools.build_closure_report import _current_analysis_campaigns


def test_current_analysis_campaigns_ignore_historical_failures():
    phase = {
        "phase": "ANALYZE",
        "epoch": 3,
        "source_collection_epoch": 2,
    }
    campaigns = [
        {
            "campaign_id": "old-backtest",
            "kind": "backtest",
            "status": "FAILED",
            "creation_phase": "ANALYZE",
            "phase_epoch": 2,
            "source_collection_epoch": 1,
        },
        {
            "campaign_id": "current-backtest",
            "kind": "backtest",
            "status": "COMPLETE",
            "creation_phase": "ANALYZE",
            "phase_epoch": 3,
            "source_collection_epoch": 2,
        },
        {
            "campaign_id": "collection-row",
            "kind": "backtest",
            "status": "FAILED",
            "creation_phase": "COLLECT",
            "phase_epoch": 3,
            "source_collection_epoch": 2,
        },
    ]

    selected = _current_analysis_campaigns(campaigns, phase)

    assert [row["campaign_id"] for row in selected] == ["current-backtest"]


def test_current_analysis_campaigns_fail_closed_outside_analyze():
    assert _current_analysis_campaigns([], {"phase": "COLLECT", "epoch": 3}) == []

import pytest

from hl_observer.control_plane.module_pnl_proof import prove_module


def test_proof_is_safe_only_and_net_of_costs():
    result = prove_module(
        "lead_lag",
        [{
            "quality_status": "SAFE",
            "replay_compatible": True,
            "gross_pnl": 10,
            "fees": 2,
            "slippage": 1,
            "funding_financing": 1,
        }],
    )
    assert result["net_pnl"] == 6
    assert result["threshold_met"]


def test_default_threshold_is_current_five_usd_daily_contract():
    result = prove_module(
        "lead_lag",
        [{
            "quality_status": "SAFE",
            "replay_compatible": True,
            "gross_pnl": 6,
            "fees": 1,
            "slippage": 0,
            "funding_financing": 0,
        }],
    )
    assert result["threshold_usd"] == 5.0
    assert result["threshold_met"]


def test_rejects_partial():
    with pytest.raises(ValueError):
        prove_module(
            "lead_lag",
            [{"quality_status": "PARTIAL", "replay_compatible": True}],
        )


def test_independent_verdict_classifies_missing_and_non_safe():
    from hl_observer.control_plane.module_pnl_proof import independent_module_verdict

    assert independent_module_verdict("lead_lag", [])["status"] == "MORE_DATA"
    result = independent_module_verdict(
        "lead_lag",
        [{"quality_status": "PARTIAL", "replay_compatible": True}],
    )
    assert result["status"] == "UNMEASURABLE"

def test_independent_verdict_emits_certificate_without_aggregation():
    from hl_observer.control_plane.module_pnl_proof import independent_module_verdict

    result = independent_module_verdict(
        "lead_lag",
        [{
            "quality_status": "SAFE",
            "replay_compatible": True,
            "gross_pnl": 10,
            "fees": 2,
            "slippage": 1,
            "funding_financing": 1,
        }],
    )
    assert result["status"] == "PROVEN"
    assert len(result["certificate_digest"]) == 64

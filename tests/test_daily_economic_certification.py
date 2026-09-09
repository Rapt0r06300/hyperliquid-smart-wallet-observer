from __future__ import annotations

from hl_observer.ops.daily_economic_certification import (
    MIN_FORWARD_OBSERVATION_SECONDS,
    TARGET_NET_USD_PER_DAY,
    apply_daily_gate,
)


def _base_certified() -> dict:
    return {
        "family": "lead_lag",
        "status": "CERTIFIED",
        "certified": True,
        "reasons": [],
    }


def _payload(*, net: float, seconds: float) -> dict:
    return {
        "family": "lead_lag",
        "forward": {
            "net_pnl_usd": net,
            "observation_seconds": seconds,
            "post_freeze": True,
        },
    }


def test_daily_gate_accepts_four_net_dollars_over_one_full_forward_day() -> None:
    result = apply_daily_gate(
        _base_certified(),
        _payload(net=4.0, seconds=86_400.0),
    )
    assert MIN_FORWARD_OBSERVATION_SECONDS == 86_400.0
    assert TARGET_NET_USD_PER_DAY == 4.0
    assert result["certified"] is True
    assert result["forward_net_pnl_usd_per_day"] == 4.0
    assert result["daily_target_reached"] is True
    assert result["reasons"] == []


def test_daily_gate_refuses_short_window_even_if_annualized_rate_looks_large() -> None:
    result = apply_daily_gate(
        _base_certified(),
        _payload(net=1.0, seconds=3_600.0),
    )
    assert result["certified"] is False
    assert "FORWARD_DAILY_PROOF_WINDOW_TOO_SHORT" in result["reasons"]


def test_daily_gate_refuses_below_four_dollars_per_day() -> None:
    result = apply_daily_gate(
        _base_certified(),
        _payload(net=6.0, seconds=172_800.0),
    )
    assert result["forward_net_pnl_usd_per_day"] == 3.0
    assert result["certified"] is False
    assert "TARGET_NET_USD_PER_DAY_NOT_REACHED" in result["reasons"]


def test_daily_gate_fails_closed_when_forward_duration_is_missing() -> None:
    payload = _payload(net=10.0, seconds=86_400.0)
    payload["forward"].pop("observation_seconds")
    result = apply_daily_gate(_base_certified(), payload)
    assert result["certified"] is False
    assert result["forward_net_pnl_usd_per_day"] is None
    assert "FORWARD_OBSERVATION_DURATION_MISSING" in result["reasons"]


def test_daily_gate_never_upgrades_a_failed_base_certification() -> None:
    base = _base_certified()
    base.update({"certified": False, "status": "NO_GO", "reasons": ["PLACEBO_NOT_BEATEN"]})
    result = apply_daily_gate(base, _payload(net=20.0, seconds=86_400.0))
    assert result["certified"] is False
    assert result["status"] == "NO_GO"
    assert "PLACEBO_NOT_BEATEN" in result["reasons"]

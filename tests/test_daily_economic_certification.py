from __future__ import annotations

from hl_observer.ops.daily_economic_certification import (
    MIN_FORWARD_COVERAGE_RATIO,
    MIN_FORWARD_OBSERVATION_SECONDS,
    TARGET_NET_USD_PER_DAY,
    apply_daily_gate,
)

FREEZE_MS = 1_800_000_000_000


def _base_certified() -> dict:
    return {
        "family": "lead_lag",
        "status": "CERTIFIED",
        "certified": True,
        "reasons": [],
    }


def _payload(*, net: float, seconds: float, coverage_ratio: float = 1.0) -> dict:
    start_ms = FREEZE_MS + 1_000
    end_ms = start_ms + int(seconds * 1_000)
    return {
        "family": "lead_lag",
        "parameter_freeze": {"frozen_at_ms": FREEZE_MS},
        "forward": {
            "net_pnl_usd": net,
            "observation_start_ms": start_ms,
            "observation_end_ms": end_ms,
            "observation_seconds": seconds,
            "observation_coverage_ratio": coverage_ratio,
            "observation_coverage_verified": True,
            "observation_source": "collector-heartbeat-journal-v1",
            "post_freeze": True,
        },
    }


def test_daily_gate_accepts_four_net_dollars_over_one_full_verified_forward_day() -> None:
    result = apply_daily_gate(_base_certified(), _payload(net=4.0, seconds=86_400.0))
    assert MIN_FORWARD_OBSERVATION_SECONDS == 86_400.0
    assert MIN_FORWARD_COVERAGE_RATIO == 0.99
    assert TARGET_NET_USD_PER_DAY == 4.0
    assert result["certified"] is True
    assert result["forward_net_pnl_usd_per_day"] == 4.0
    assert result["daily_target_reached"] is True
    assert result["reasons"] == []


def test_daily_gate_refuses_short_window_even_if_annualized_rate_looks_large() -> None:
    result = apply_daily_gate(_base_certified(), _payload(net=1.0, seconds=3_600.0))
    assert result["certified"] is False
    assert "FORWARD_DAILY_PROOF_WINDOW_TOO_SHORT" in result["reasons"]


def test_daily_gate_refuses_below_four_dollars_per_day() -> None:
    result = apply_daily_gate(_base_certified(), _payload(net=6.0, seconds=172_800.0))
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


def test_daily_gate_recomputes_clock_and_refuses_tampered_duration() -> None:
    payload = _payload(net=4.0, seconds=86_400.0)
    payload["forward"]["observation_end_ms"] = payload["forward"]["observation_start_ms"] + 3_600_000
    result = apply_daily_gate(_base_certified(), payload)
    assert result["certified"] is False
    assert "FORWARD_OBSERVATION_DURATION_MISMATCH" in result["reasons"]


def test_daily_gate_refuses_observation_that_starts_before_freeze() -> None:
    payload = _payload(net=4.0, seconds=86_400.0)
    payload["forward"]["observation_start_ms"] = FREEZE_MS - 1
    result = apply_daily_gate(_base_certified(), payload)
    assert result["certified"] is False
    assert "FORWARD_OBSERVATION_NOT_STRICTLY_POST_FREEZE" in result["reasons"]


def test_daily_gate_refuses_unverified_or_incomplete_collector_coverage() -> None:
    low = apply_daily_gate(_base_certified(), _payload(net=4.0, seconds=86_400.0, coverage_ratio=0.5))
    assert low["certified"] is False
    assert "FORWARD_OBSERVATION_COVERAGE_TOO_LOW" in low["reasons"]

    payload = _payload(net=4.0, seconds=86_400.0)
    payload["forward"]["observation_coverage_verified"] = False
    unverified = apply_daily_gate(_base_certified(), payload)
    assert unverified["certified"] is False
    assert "FORWARD_OBSERVATION_COVERAGE_UNVERIFIED" in unverified["reasons"]


def test_daily_gate_never_upgrades_a_failed_base_certification() -> None:
    base = _base_certified()
    base.update({"certified": False, "status": "NO_GO", "reasons": ["PLACEBO_NOT_BEATEN"]})
    result = apply_daily_gate(base, _payload(net=20.0, seconds=86_400.0))
    assert result["certified"] is False
    assert result["status"] == "NO_GO"
    assert "PLACEBO_NOT_BEATEN" in result["reasons"]

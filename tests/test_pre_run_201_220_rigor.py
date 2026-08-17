from __future__ import annotations

from datetime import timezone
from pathlib import Path

import pytest

from hl_observer.research.pre_run_201_220 import (
    ExclusiveLaunchGuard,
    detecter_change_points,
    minimum_track_record,
    parse_decimal_invariant,
    parse_utc_invariant,
    retry_file_lock,
    surveiller_drift_execution,
    verifier_budget_performance,
    verifier_reserve_tests_rares,
)


def test_aud_201_minimum_track_record_fail_closed_and_sufficient():
    assert minimum_track_record([])["suffisant"] is False
    flat = minimum_track_record([0.0] * 30)
    assert flat["n_requis"] is None and flat["raison"] == "EDGE_NUL"
    stable = minimum_track_record([1.0] * 30)
    assert stable["suffisant"] is True and stable["n_requis"] >= 20


def test_aud_202_execution_drift_requires_all_metrics_and_flags_harm():
    base = {"cost_bps": 10.0, "fill_rate": 0.9, "latency_ms": 100.0}
    ok = surveiller_drift_execution(base, dict(base))
    assert ok["stable"] is True and ok["missing"] == []
    ko = surveiller_drift_execution(base, {"cost_bps": 15.0, "fill_rate": 0.7, "latency_ms": 140.0})
    assert ko["stable"] is False
    assert all(v["drift_nuisible"] for v in ko["metrics"].values())
    assert surveiller_drift_execution(base, {"cost_bps": 10.0})["stable"] is False


def test_aud_203_change_point_detects_regime_break_without_short_series_claim():
    short = detecter_change_points([1.0] * 5)
    assert short["change"] is False and short["raison"] == "SERIE_TROP_COURTE"
    xs = [0.0, 0.1, -0.1, 0.0] * 5 + [5.0, 5.1, 4.9, 5.0] * 5
    r = detecter_change_points(xs, min_segment=8, z_threshold=3.0)
    assert r["change"] is True
    assert 16 <= r["index"] <= 24


def test_aud_213_rare_reserve_is_never_a_tuning_gradient():
    tests = [
        {"id": "flash-crash", "tag": "flash_crash", "rare": True, "used_for_tuning": False},
        {"id": "outage", "tag": "venue_outage", "rare": True, "used_for_tuning": False},
    ]
    assert verifier_reserve_tests_rares(tests, tags_requis=["flash_crash", "venue_outage"])["ok"] is True
    tests[0]["used_for_tuning"] = True
    assert verifier_reserve_tests_rares(tests, tags_requis=["flash_crash"])["ok"] is False


def test_aud_214_performance_budget_is_fail_closed():
    budgets = {"ram_mb": 500.0, "latency_ms": 50.0}
    assert verifier_budget_performance({"ram_mb": 400.0, "latency_ms": 20.0}, budgets)["ok"] is True
    assert verifier_budget_performance({"ram_mb": 600.0, "latency_ms": 20.0}, budgets)["ok"] is False
    assert verifier_budget_performance({"ram_mb": 400.0}, budgets)["ok"] is False


def test_aud_217_simultaneous_double_click_has_single_owner(tmp_path: Path):
    path = tmp_path / "run.lock"
    a = ExclusiveLaunchGuard(path)
    b = ExclusiveLaunchGuard(path)
    assert a.acquire() is True
    try:
        assert b.acquire() is False
    finally:
        a.release()
    assert b.acquire() is True
    b.release()


def test_aud_218_antivirus_file_lock_retry_is_bounded():
    state = {"n": 0}

    def op():
        state["n"] += 1
        if state["n"] < 3:
            raise PermissionError("locked")
        return "ok"

    r = retry_file_lock(op, attempts=4, sleeper=lambda _: None)
    assert r == {"ok": True, "attempts": 3, "value": "ok"}

    def always_locked():
        raise PermissionError("locked")

    ko = retry_file_lock(always_locked, attempts=2, sleeper=lambda _: None)
    assert ko["ok"] is False and ko["attempts"] == 2


def test_aud_219_locale_and_timezone_are_explicit():
    assert str(parse_decimal_invariant("1234.50")) == "1234.50"
    with pytest.raises(ValueError, match="DECIMAL_COMMA_AMBIGUOUS"):
        parse_decimal_invariant("1234,50")
    dt = parse_utc_invariant("2026-08-17T20:00:00+02:00")
    assert dt.tzinfo == timezone.utc and dt.hour == 18
    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        parse_utc_invariant("2026-08-17T20:00:00")

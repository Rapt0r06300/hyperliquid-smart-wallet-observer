from __future__ import annotations

from hl_observer.risk.microstructure_guard import (
    MicrostructureGuardConfig,
    evaluate_microstructure_guard,
    side_conflicts_with_obi,
)


def test_microstructure_guard_accepts_liquid_aligned_book() -> None:
    decision = evaluate_microstructure_guard(
        side="LONG",
        needed_usd=50.0,
        bids=((99.9, 20.0), (99.8, 20.0), (99.7, 20.0)),
        asks=((100.1, 30.0), (100.2, 30.0), (100.3, 30.0)),
        recent_returns=[0.001, -0.0005, 0.0008, -0.0004, 0.0012],
        confidence_samples=([(0.7, True)] * 7) + ([(0.7, False)] * 3) + ([(0.3, True)] * 3) + ([(0.3, False)] * 7),
        config=MicrostructureGuardConfig(max_spread_bps=40.0),
    )

    assert decision.authoritative_ok is True
    assert decision.ok is True
    assert decision.top1_usd and decision.top1_usd > 20.0
    assert "CALIBRATION_SAMPLE_INSUFFICIENT" not in decision.reasons


def test_microstructure_guard_blocks_thin_top_of_book() -> None:
    decision = evaluate_microstructure_guard(
        side="LONG",
        needed_usd=50.0,
        bids=((99.9, 5.0), (99.8, 5.0), (99.7, 5.0)),
        asks=((100.1, 0.05), (100.2, 0.05), (100.3, 0.05)),
    )

    assert decision.authoritative_ok is False
    assert "TOP1_TOO_THIN" in decision.authoritative_reasons


def test_microstructure_guard_blocks_wide_spread() -> None:
    decision = evaluate_microstructure_guard(
        side="LONG",
        needed_usd=50.0,
        bids=((90.0, 50.0), (89.9, 50.0), (89.8, 50.0)),
        asks=((100.0, 50.0), (100.1, 50.0), (100.2, 50.0)),
        config=MicrostructureGuardConfig(max_spread_bps=50.0),
    )

    assert decision.authoritative_ok is False
    assert "SPREAD_TOO_WIDE" in decision.authoritative_reasons


def test_microstructure_guard_blocks_obi_conflict() -> None:
    decision = evaluate_microstructure_guard(
        side="LONG",
        needed_usd=50.0,
        bids=((99.9, 1.0), (99.8, 1.0), (99.7, 1.0)),
        asks=((100.1, 100.0), (100.2, 100.0), (100.3, 100.0)),
        config=MicrostructureGuardConfig(max_spread_bps=80.0, obi_conflict_strength=0.35),
    )

    assert decision.obi_signal == "SHORT_BIAS"
    assert decision.authoritative_ok is False
    assert "OBI_CONFLICTS_WITH_SIDE" in decision.authoritative_reasons


def test_microstructure_guard_blocks_high_var_cvar() -> None:
    decision = evaluate_microstructure_guard(
        side="SHORT",
        needed_usd=50.0,
        bids=((99.9, 50.0), (99.8, 50.0), (99.7, 50.0)),
        asks=((100.1, 50.0), (100.2, 50.0), (100.3, 50.0)),
        recent_returns=[0.001, -0.04, -0.03, 0.002, -0.02],
        config=MicrostructureGuardConfig(max_var_fraction=0.01, max_cvar_fraction=0.015),
    )

    assert decision.authoritative_ok is False
    assert "VAR_TOO_HIGH" in decision.authoritative_reasons
    assert "CVAR_TOO_HIGH" in decision.authoritative_reasons


def test_microstructure_guard_missing_book_is_evidence_not_trade_data() -> None:
    decision = evaluate_microstructure_guard(
        side="LONG",
        needed_usd=50.0,
        asks=(),
        bids=(),
        recent_returns=[0.001, -0.001],
    )

    assert "BOOK_MISSING" in decision.reasons
    assert decision.top1_usd is None
    assert decision.authoritative_ok is True


def test_side_conflict_helper() -> None:
    assert side_conflicts_with_obi("LONG", "SHORT_BIAS", 0.5, 0.35) is True
    assert side_conflicts_with_obi("SHORT", "LONG_BIAS", 0.5, 0.35) is True
    assert side_conflicts_with_obi("LONG", "LONG_BIAS", 0.5, 0.35) is False
    assert side_conflicts_with_obi("LONG", "SHORT_BIAS", 0.1, 0.35) is False

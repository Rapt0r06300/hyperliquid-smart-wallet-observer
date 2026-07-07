from __future__ import annotations

from hl_observer.copying.runtime_v9_adapter import (
    attach_v9_runtime_diagnostics,
    build_signal_candidate_from_event,
)


def _event(**overrides):
    event = {
        "delta_key": "d1",
        "paper_ref": "paper:d1",
        "wallet_address": "0x" + "1" * 40,
        "coin": "ETH",
        "leader_action": "OPEN_LONG",
        "leader_side": "LONG",
        "observed_at_ms": 1_700_000_000_000,
        "leader_price": 2_000.0,
        "signal_age_ms": 500,
        "leader_score": 95.0,
        "opportunity_score": 92.0,
        "edge_remaining_bps": 120.0,
        "spread_bps": 2.0,
        "slippage_bps": 3.0,
        "copied_notional_usdt": 25.0,
    }
    event.update(overrides)
    return event


def test_runtime_adapter_builds_signal_candidate_from_replay_event() -> None:
    signal = build_signal_candidate_from_event(_event(), current_ms=1_700_000_000_500)

    assert signal.coin == "ETH"
    assert signal.side == "long"
    assert signal.signal_type == "open"
    assert signal.observed_price == 2_000.0
    assert signal.edge_remaining_bps == 120.0
    assert signal.wallet_score == 95.0
    assert signal.signal_score == 92.0


def test_runtime_adapter_exposes_data_gap_when_only_all_mids_available() -> None:
    event = attach_v9_runtime_diagnostics(
        _event(),
        current_ms=1_700_000_000_500,
        all_mids={"ETH": 2_000.0},
        run_id="test-gap",
    )

    assert event["v9_accepted"] is False
    assert event["v9_evidence_hash"].startswith("ev:")
    assert event["v9_pipeline"]["market_quality_mode"] == "NO_TRADE"
    assert "MISSING_BOOK_SIDE" in event["v9_pipeline"]["market_quality_reasons"]
    assert any("data gap" in reason for reason in event["v9_reasons"])


def test_runtime_adapter_can_pass_with_real_l2book_features() -> None:
    l2_book = {
        "levels": [
            [{"px": "1999", "sz": "20"}, {"px": "1998", "sz": "20"}],
            [{"px": "2001", "sz": "20"}, {"px": "2002", "sz": "20"}],
        ]
    }
    event = attach_v9_runtime_diagnostics(
        _event(),
        current_ms=1_700_000_000_500,
        all_mids={"ETH": 2_000.0},
        l2_book=l2_book,
        candles=[
            {"T": 1_699_999_000_000, "h": "2010", "l": "1990", "c": "2000"},
            {"T": 1_699_999_060_000, "h": "2012", "l": "1992", "c": "2002"},
            {"T": 1_699_999_120_000, "h": "2014", "l": "1994", "c": "2004"},
        ],
        run_id="test-pass",
    )

    assert event["v9_accepted"] is True
    assert event["v9_decision"] == "PAPER_TRADE"
    assert event["v9_pipeline"]["paper_notional_usdc"] == 25.0
    assert event["v9_pipeline"]["feature_hash"].startswith("feat:")


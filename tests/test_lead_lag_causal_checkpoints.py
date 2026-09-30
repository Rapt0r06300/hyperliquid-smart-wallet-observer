from __future__ import annotations

import pytest

from hl_observer.backtesting.lead_lag_queue_replay import (
    SHOCK_COOLDOWN_MS,
    SHOCK_THRESHOLD_BPS,
    SHOCK_WINDOW_MS,
    detect_rolling_shocks,
)
from hl_observer.collection.lead_lag_causal_checkpoints import (
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    ECONOMIC_SHOCK_THRESHOLD_BPS,
    LeadLagCheckpointConfig,
    LeadLagCheckpointRequest,
    RollingShockCheckpointDetector,
    validate_l2_book_payload,
)
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind
from hl_observer.simulation.lead_lag_l2_history import snapshot_from_tick


BASE_WALL_MS = 1_800_000_000_000
BASE_MONO_NS = 9_000_000_000


def _observe(
    detector: RollingShockCheckpointDetector,
    offset_ms: int,
    price: float,
):
    return detector.observe(
        coin="ETH",
        price=price,
        received_monotonic_ns=BASE_MONO_NS + offset_ms * 1_000_000,
        received_wall_ms=BASE_WALL_MS + offset_ms,
        event_id=f"bin-trade:{offset_ms}",
    )


def _request() -> LeadLagCheckpointRequest:
    return LeadLagCheckpointRequest(
        coin="ETH",
        trigger_event_id="bin-trade:1",
        trigger_ts_ms=BASE_WALL_MS + 100,
        trigger_monotonic_ns=BASE_MONO_NS + 100_000_000,
        window_start_ts_ms=BASE_WALL_MS,
        lead_start_price=100.0,
        lead_trigger_price=100.25,
        lead_shock_bps=25.0,
        direction=1,
        threshold_class="ECONOMIC",
    )


def _payload() -> dict:
    return {
        "coin": "ETH",
        "time": BASE_WALL_MS + 110,
        "levels": [
            [{"px": "100.00", "sz": "2"}, {"px": "99.90", "sz": "3"}],
            [{"px": "100.10", "sz": "4"}, {"px": "100.20", "sz": "5"}],
        ],
    }


def test_checkpoint_defaults_match_frozen_economic_replay() -> None:
    config = LeadLagCheckpointConfig()
    assert config.window_ms == SHOCK_WINDOW_MS
    assert config.economic_threshold_bps == SHOCK_THRESHOLD_BPS
    assert config.cooldown_ms == SHOCK_COOLDOWN_MS
    assert config.diagnostic_threshold_bps == DIAGNOSTIC_SHOCK_THRESHOLD_BPS
    assert ECONOMIC_SHOCK_THRESHOLD_BPS == SHOCK_THRESHOLD_BPS


def test_streaming_detector_matches_offline_economic_shocks_without_lookahead() -> None:
    detector = RollingShockCheckpointDetector()
    rows = [
        (0, 100.0),
        (100, 100.05),
        (200, 100.10),  # diagnostic request only
        (300, 100.25),  # economic request must not be suppressed by diagnostic
        (5_400, 100.0),
        (5_500, 100.25),
    ]
    requests = [_observe(detector, offset, price) for offset, price in rows]
    economic_offsets = [
        request.trigger_ts_ms - BASE_WALL_MS
        for request in requests
        if request is not None and request.economic_threshold_crossed
    ]
    offline = detect_rolling_shocks(
        [
            (BASE_MONO_NS + offset * 1_000_000, price)
            for offset, price in rows
        ],
        threshold_bps=SHOCK_THRESHOLD_BPS,
    )
    expected_offsets = [
        shock["trigger_ts_ms"] - BASE_MONO_NS // 1_000_000
        for shock in offline
    ]
    assert economic_offsets == expected_offsets == [300, 5_500]
    assert requests[1] is None
    assert requests[2] is not None
    assert requests[2].threshold_class == "DIAGNOSTIC"


def test_detector_rejects_out_of_order_wrong_coin_and_preserves_economic_budget() -> None:
    config = LeadLagCheckpointConfig(
        max_requests_per_minute=3,
        max_diagnostic_requests_per_minute=1,
        economic_request_reserve=1,
        cooldown_ms=0,
    )
    detector = RollingShockCheckpointDetector(config)
    assert _observe(detector, 0, 100.0) is None
    diagnostic = _observe(detector, 100, 100.10)
    assert diagnostic is not None and diagnostic.threshold_class == "DIAGNOSTIC"
    # Diagnostic budget is exhausted, but an economic shock still owns reserve.
    economic = _observe(detector, 200, 100.25)
    assert economic is not None and economic.threshold_class == "ECONOMIC"
    assert _observe(detector, 150, 101.0) is None  # out-of-order monotonic clock
    assert detector.observe(
        coin="BTC",
        price=200.0,
        received_monotonic_ns=BASE_MONO_NS + 300_000_000,
        received_wall_ms=BASE_WALL_MS + 300,
        event_id="btc",
    ) is None


def test_real_l2_validation_rejects_missing_crossed_and_wrong_coin() -> None:
    book = validate_l2_book_payload(_payload(), expected_coin="ETH")
    assert book.bid_depth_usd == pytest.approx(499.7)
    assert book.ask_depth_usd == pytest.approx(901.4)
    assert book.wrapped_message(_request())["causal_checkpoint"][
        "economic_threshold_crossed"
    ] is True

    invalid = _payload()
    invalid["levels"] = [[], []]
    try:
        validate_l2_book_payload(invalid, expected_coin="ETH")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:  # pragma: no cover - explicit fail-closed assertion
        raise AssertionError("empty L2 book was accepted")

    crossed = _payload()
    crossed["levels"][1][0]["px"] = "99.00"
    try:
        validate_l2_book_payload(crossed, expected_coin="ETH")
    except ValueError as exc:
        assert "crossed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("crossed L2 book was accepted")

    try:
        validate_l2_book_payload(_payload(), expected_coin="BTC")
    except ValueError as exc:
        assert "mismatch" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("wrong-coin L2 book was accepted")


def test_checkpoint_tick_is_causal_replay_compatible_and_read_only() -> None:
    request = _request()
    book = validate_l2_book_payload(_payload(), expected_coin=request.coin)
    received_ms = BASE_WALL_MS + 120
    envelope = TickEnvelope(
        source_id="hyperliquid_mainnet_readonly",
        channel="l2Book",
        instrument="ETH",
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload=book.wrapped_message(request),
        exchange_ts_ms=book.exchange_ts_ms,
        received_ts_ms=received_ms,
        local_monotonic_ns=BASE_MONO_NS + 120_000_000,
        connection_id="hl-info-lead-lag-checkpoint",
        sequence=7,
        provenance={
            "endpoint": "/info",
            "request_type": "l2Book",
            "access": "read_only",
            "purpose": "lead_lag_causal_checkpoint",
        },
        parsed_summary={
            "feed_quality_score": 100.0,
            "data_gate_ready": True,
            "quality_reasons": [],
        },
    )
    record = envelope.as_record(written_ts_ms=received_ms + 5)
    snapshot = snapshot_from_tick(record)

    assert record["read_only"] is True
    assert record["real_execution"] is False
    assert record["provenance"]["endpoint"] == "/info"
    assert snapshot is not None
    assert snapshot["coin"] == "ETH"
    assert snapshot["ts_ms"] == received_ms + 5
    assert snapshot["bid"] == 100.0
    assert snapshot["ask"] == 100.1
    assert snapshot["data_gate_ready"] is True
    assert snapshot["source"] == "hyperliquid:recorded:l2Book"

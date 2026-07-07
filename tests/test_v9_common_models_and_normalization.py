import pytest
from pydantic import ValidationError

from hl_observer.models import DataQuality, Position, PositionAction, SourceMeta, Wallet
from hl_observer.normalization import (
    classify_fill_action,
    classify_position_delta,
    infer_fill_from_position_delta,
    normalize_position_delta,
    reconcile_positions,
)


def _meta(**overrides):
    data = {
        "source_endpoint": "/info",
        "local_received_ts": 1000,
        "raw_hash": "abc",
        "data_quality": DataQuality.OK,
    }
    data.update(overrides)
    return SourceMeta(**data)


def test_wallet_model_rejects_truncated_and_invalid_addresses():
    with pytest.raises(ValidationError, match="truncated wallet"):
        Wallet(address="0xabc...def", meta=_meta())
    with pytest.raises(ValidationError, match="0x \\+ 40 hex"):
        Wallet(address="0x123", meta=_meta())


def test_position_delta_classification_open_add_reduce_close_and_flip():
    assert classify_position_delta(0, 1) == PositionAction.OPEN_LONG
    assert classify_position_delta(0, -1) == PositionAction.OPEN_SHORT
    assert classify_position_delta(1, 2) == PositionAction.INCREASE
    assert classify_position_delta(-1, -2) == PositionAction.INCREASE
    assert classify_position_delta(2, 1) == PositionAction.REDUCE
    assert classify_position_delta(-2, -1) == PositionAction.REDUCE
    assert classify_position_delta(1, 0) == PositionAction.CLOSE_LONG
    assert classify_position_delta(-1, 0) == PositionAction.CLOSE_SHORT
    assert classify_position_delta(1, -1) == PositionAction.UNKNOWN
    assert classify_position_delta(-1, 1) == PositionAction.UNKNOWN


def test_unknown_delta_is_not_allowed_for_paper_intent():
    delta = normalize_position_delta(
        wallet="0x" + "a" * 40,
        coin="HYPE",
        previous_size=1.0,
        current_size=-1.0,
        meta=_meta(),
    )

    assert delta.action == PositionAction.UNKNOWN
    assert delta.confidence == 0.0
    assert "UNKNOWN_DELTA_NO_PAPER_INTENT" in delta.warnings


def test_fill_classification_requires_result_for_close():
    missing_close = classify_fill_action(direction="Close Long", start_position=1.0)
    closed = classify_fill_action(direction="Close Long", start_position=1.0, resulting_position=0.0)
    reduced = classify_fill_action(direction="Close Short", start_position=-2.0, resulting_position=-1.0)

    assert missing_close.allowed_for_paper is False
    assert missing_close.action == PositionAction.UNKNOWN
    assert closed.action == PositionAction.CLOSE_LONG
    assert reduced.action == PositionAction.REDUCE


def test_reconcile_rest_ws_divergence_returns_no_trade():
    rest = [
        Position(wallet="0x" + "a" * 40, coin="BTC", signed_size=1.0, meta=_meta()),
    ]
    ws = [
        Position(wallet="0x" + "a" * 40, coin="BTC", signed_size=1.5, meta=_meta(source_channel="ws/userFills", source_endpoint=None)),
    ]

    result = reconcile_positions(rest, ws, max_abs_size_diff=0.01)

    assert result.allowed_for_paper is False
    assert result.reason == "RECONCILIATION_DIVERGENCE_NO_TRADE"


def test_fill_inference_is_low_confidence_and_real_price_only():
    inferred = infer_fill_from_position_delta(
        wallet="0x" + "b" * 40,
        coin="ETH",
        previous_size=0.0,
        current_size=2.0,
        mark_price=2500.0,
        observed_at_ms=1234,
        meta=_meta(raw_hash="position-poll"),
    )

    assert inferred.allowed_for_paper is True
    assert inferred.action == PositionAction.OPEN_LONG
    assert inferred.confidence == 0.35
    assert inferred.fill is not None
    assert inferred.fill.price == 2500.0
    assert inferred.reason == "INFERRED_FROM_POSITION_POLLING_LOW_CONFIDENCE"

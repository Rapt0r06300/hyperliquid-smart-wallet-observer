from hl_observer.wallets.position_delta_engine import (
    PositionAction,
    PositionSide,
    build_position_delta_from_fill,
)

VALID_WALLET = "0x" + "3" * 40


def test_position_delta_open_detected():
    delta = build_position_delta_from_fill(
        VALID_WALLET,
        {"coin": "BTC", "time": 1, "side": "B", "px": "100", "sz": "1"},
        previous_size=0,
    )

    assert delta.action == PositionAction.OPEN
    assert delta.new_side == PositionSide.LONG
    assert delta.delta_notional_usdc == 100


def test_position_delta_add_detected():
    delta = build_position_delta_from_fill(
        VALID_WALLET,
        {"coin": "BTC", "time": 1, "side": "B", "px": "100", "sz": "0.5"},
        previous_size=1,
    )

    assert delta.action == PositionAction.ADD
    assert delta.new_size == 1.5


def test_position_delta_reduce_detected():
    delta = build_position_delta_from_fill(
        VALID_WALLET,
        {"coin": "BTC", "time": 1, "side": "A", "px": "100", "sz": "0.25"},
        previous_size=1,
    )

    assert delta.action == PositionAction.REDUCE
    assert delta.new_size == 0.75


def test_position_delta_close_detected():
    delta = build_position_delta_from_fill(
        VALID_WALLET,
        {"coin": "BTC", "time": 1, "side": "A", "px": "100", "sz": "1"},
        previous_size=1,
    )

    assert delta.action == PositionAction.CLOSE
    assert delta.new_side == PositionSide.FLAT


def test_position_delta_flip_detected():
    delta = build_position_delta_from_fill(
        VALID_WALLET,
        {"coin": "BTC", "time": 1, "side": "A", "px": "100", "sz": "2"},
        previous_size=1,
    )

    assert delta.action == PositionAction.FLIP
    assert delta.previous_side == PositionSide.LONG
    assert delta.new_side == PositionSide.SHORT


def test_position_delta_unknown_when_direction_unclear():
    delta = build_position_delta_from_fill(
        VALID_WALLET,
        {"coin": "BTC", "time": 1, "px": "100", "sz": "1"},
        previous_size=1,
    )

    assert delta.action == PositionAction.UNKNOWN
    assert "direction_unclear" in delta.notes


def test_position_delta_confidence_low_when_missing_fields():
    delta = build_position_delta_from_fill(
        VALID_WALLET,
        {"coin": "BTC", "time": 1, "px": "100"},
        previous_size=1,
    )

    assert delta.confidence_score < 0.5
    assert "missing_size" in delta.notes

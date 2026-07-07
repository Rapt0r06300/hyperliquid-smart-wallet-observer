from hl_observer.wallets.position_delta_engine import (
    PositionAction,
    build_position_delta_from_fill,
    classify_action,
    classify_lifecycle,
    detect_liquidation,
)


# ---- base states preserved (classify_lifecycle delegates to classify_action) ----

def test_base_states_match_classify_action():
    cases = [(0.0, 10.0), (10.0, 20.0), (20.0, 10.0), (10.0, 0.0), (10.0, -10.0)]
    for prev, new in cases:
        assert classify_lifecycle(prev, new) == classify_action(prev, new)


def test_base_open_add_reduce_close_flip():
    assert classify_lifecycle(0.0, 10.0) == PositionAction.OPEN
    assert classify_lifecycle(10.0, 20.0) == PositionAction.ADD
    assert classify_lifecycle(20.0, 10.0) == PositionAction.REDUCE
    assert classify_lifecycle(10.0, 0.0) == PositionAction.CLOSE
    assert classify_lifecycle(10.0, -5.0) == PositionAction.FLIP


def test_direction_unclear_is_unknown():
    assert classify_lifecycle(10.0, 10.0, direction_unclear=True) == PositionAction.UNKNOWN


# ---- liquidation detection (real fields only) ----

def test_detect_liquidation_field():
    assert detect_liquidation({"liquidation": True}) is True
    assert detect_liquidation({"liquidation": {"liquidatedUser": "0xabc"}}) is True


def test_detect_liquidation_dir_string():
    assert detect_liquidation({"dir": "Close Long (Liquidation)"}) is True
    assert detect_liquidation({"dir": "Open Long"}) is False


def test_detect_liquidation_robust_on_bad_input():
    assert detect_liquidation(None) is False
    assert detect_liquidation({}) is False
    assert detect_liquidation({"side": "b"}) is False


# ---- LIQUIDATION only overlays REDUCE/CLOSE ----

def test_liquidation_overlays_close():
    fill = {"liquidation": True}
    assert classify_lifecycle(10.0, 0.0, fill=fill) == PositionAction.LIQUIDATION
    assert classify_lifecycle(20.0, 10.0, fill=fill) == PositionAction.LIQUIDATION


def test_liquidation_flag_does_not_change_open_or_add():
    fill = {"liquidation": True}
    # an OPEN/ADD is never relabelled LIQUIDATION (liquidation reduces/closes)
    assert classify_lifecycle(0.0, 10.0, fill=fill) == PositionAction.OPEN
    assert classify_lifecycle(10.0, 20.0, fill=fill) == PositionAction.ADD


# ---- real wiring through build_position_delta_from_fill ----

def test_build_delta_tags_liquidation_on_close():
    fill = {"coin": "BTC", "px": "100", "sz": "10", "side": "a", "time": 1, "liquidation": True}
    rec = build_position_delta_from_fill("0xwallet", fill, previous_size=10.0)
    assert rec.new_size == 0.0
    assert rec.action == PositionAction.LIQUIDATION


def test_build_delta_normal_close_unchanged():
    fill = {"coin": "BTC", "px": "100", "sz": "10", "side": "a", "time": 1}
    rec = build_position_delta_from_fill("0xwallet", fill, previous_size=10.0)
    assert rec.action == PositionAction.CLOSE  # no liquidation flag -> unchanged


def test_build_delta_open_unaffected():
    fill = {"coin": "ETH", "px": "50", "sz": "4", "side": "b", "time": 1}
    rec = build_position_delta_from_fill("0xwallet", fill, previous_size=0.0)
    assert rec.action == PositionAction.OPEN

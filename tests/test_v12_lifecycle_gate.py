from hl_observer.signals.lifecycle_gate import lifecycle_no_trade_code
from hl_observer.signals.no_trade_taxonomy import resolve
from hl_observer.wallets.position_delta_engine import PositionAction


def test_unknown_maps_to_lifecycle_unknown():
    assert lifecycle_no_trade_code(PositionAction.UNKNOWN) == "LIFECYCLE_UNKNOWN"


def test_flip_maps_to_ambiguous_flip():
    assert lifecycle_no_trade_code(PositionAction.FLIP) == "AMBIGUOUS_FLIP"
    assert lifecycle_no_trade_code("flip") == "AMBIGUOUS_FLIP"  # accepts string


def test_orphan_close_only_when_no_known_position():
    assert lifecycle_no_trade_code(PositionAction.CLOSE, has_known_position=False) == "ORPHAN_CLOSE"
    assert lifecycle_no_trade_code(PositionAction.REDUCE, has_known_position=False) == "ORPHAN_CLOSE"
    assert lifecycle_no_trade_code(PositionAction.CLOSE, has_known_position=True) is None


def test_open_add_liquidation_do_not_block():
    assert lifecycle_no_trade_code(PositionAction.OPEN) is None
    assert lifecycle_no_trade_code(PositionAction.ADD) is None
    assert lifecycle_no_trade_code(PositionAction.LIQUIDATION) is None


def test_returned_codes_exist_in_taxonomy():
    for action, kw in [(PositionAction.UNKNOWN, {}), (PositionAction.FLIP, {}),
                       (PositionAction.CLOSE, {"has_known_position": False})]:
        code = lifecycle_no_trade_code(action, **kw)
        assert resolve(code).value == code

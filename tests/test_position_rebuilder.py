from hl_observer.wallets.position_delta_engine import PositionAction, PositionSide
from hl_observer.wallets.position_rebuilder import rebuild_positions_from_fills, sort_fills_by_time

VALID_WALLET = "0x" + "4" * 40


def test_position_rebuilder_sorts_fills_by_time():
    fills = [
        {"coin": "BTC", "time": 30},
        {"coin": "BTC", "time": 10},
        {"coin": "BTC", "time": 20},
    ]

    assert [fill["time"] for fill in sort_fills_by_time(fills)] == [10, 20, 30]


def test_position_rebuilder_rebuilds_latest_position():
    result = rebuild_positions_from_fills(
        VALID_WALLET,
        [
            {"coin": "BTC", "time": 10, "side": "B", "px": "100", "sz": "1"},
            {"coin": "BTC", "time": 20, "side": "A", "px": "110", "sz": "0.25"},
        ],
    )

    position = result.positions[0]
    assert position.side == PositionSide.LONG
    assert position.size == 0.75
    assert position.status == "OPEN"
    assert [delta.action for delta in result.deltas] == [PositionAction.OPEN, PositionAction.REDUCE]


def test_position_rebuilder_marks_uncertain_state_incomplete():
    result = rebuild_positions_from_fills(
        VALID_WALLET,
        [{"coin": "BTC", "time": 10, "px": "100", "sz": "1"}],
    )

    assert result.positions[0].status == "INCOMPLETE"
    assert result.deltas[0].action == PositionAction.UNKNOWN

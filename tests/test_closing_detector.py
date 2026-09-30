from hl_observer.analysis.closing_detector import detect_closings_from_deltas
from hl_observer.wallets.position_delta_engine import PositionAction, PositionDeltaRecord, PositionSide


def _delta(action: PositionAction):
    return PositionDeltaRecord(
        wallet_address="0x" + "2" * 40,
        coin="SOL",
        previous_side=PositionSide.LONG,
        new_side=PositionSide.FLAT,
        previous_size=1,
        new_size=0,
        delta_size=-1,
        action=action,
    )


def test_closing_detector_detects_partial_and_full_close():
    closings = detect_closings_from_deltas([_delta(PositionAction.REDUCE), _delta(PositionAction.CLOSE)])

    assert [event.action for event in closings] == ["REDUCE", "CLOSE"]

from hl_observer.analysis.opening_detector import detect_openings_from_deltas
from hl_observer.wallets.position_delta_engine import PositionAction, PositionDeltaRecord, PositionSide


def _delta(action: PositionAction):
    return PositionDeltaRecord(
        wallet_address="0x" + "1" * 40,
        coin="HYPE",
        previous_side=PositionSide.FLAT,
        new_side=PositionSide.LONG,
        previous_size=0,
        new_size=1,
        delta_size=1,
        action=action,
    )


def test_opening_detector_detects_open_add_reduce_close_flip():
    openings = detect_openings_from_deltas(
        [_delta(PositionAction.OPEN), _delta(PositionAction.ADD), _delta(PositionAction.REDUCE), _delta(PositionAction.CLOSE), _delta(PositionAction.FLIP)]
    )

    assert [event.action for event in openings] == ["OPEN", "ADD", "FLIP"]

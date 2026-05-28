import pytest
from hyper_smart_observer.copy_mode.delta_detector import classify_position_delta
from hyper_smart_observer.copy_mode.copy_models import DeltaAction

@pytest.mark.contract
def test_contract_delta_detector_taxonomy():
    """
    Contract test for the Delta Detector taxonomy.
    Must support all requested action types.
    """

    # Test cases for taxonomy
    # (prev_size, curr_size) -> expected_action
    cases = [
        (0, 10, DeltaAction.OPEN_LONG),
        (0, -10, DeltaAction.OPEN_SHORT),
        (10, 20, DeltaAction.INCREASE), # INCREASE is used for ADD/INCREASE in implementation
        (-10, -20, DeltaAction.INCREASE),
        (10, 5, DeltaAction.REDUCE),
        (-10, -5, DeltaAction.REDUCE),
        (10, 0, DeltaAction.CLOSE_LONG),
        (-10, 0, DeltaAction.CLOSE_SHORT),
        (10, -10, DeltaAction.UNKNOWN), # Flip is UNKNOWN by design
    ]

    for prev, curr, expected in cases:
        action, warnings = classify_position_delta(prev, curr)
        assert action == expected, f"Contract failure: ({prev} -> {curr}) should be {expected}, got {action}"

@pytest.mark.contract
def test_contract_delta_detector_ambiguity_handling():
    """
    Contract: Ambiguous deltas must return UNKNOWN.
    """
    assert classify_position_delta(10, -5)[0] == DeltaAction.UNKNOWN
    assert classify_position_delta(-10, 5)[0] == DeltaAction.UNKNOWN

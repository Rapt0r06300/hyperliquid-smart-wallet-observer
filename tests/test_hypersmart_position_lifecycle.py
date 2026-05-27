from datetime import UTC, datetime

from hyper_smart_observer.hyperliquid_client.models import PositionActionType
from hyper_smart_observer.position_lifecycle.action_classifier import classify_position_action
from hyper_smart_observer.position_lifecycle.lifecycle_builder import build_lifecycles
from hyper_smart_observer.position_lifecycle.lifecycle_models import PositionAction


def test_action_classifier_open_close_long_short_and_unknown():
    assert classify_position_action("Open Long") == PositionActionType.OPEN_LONG
    assert classify_position_action("Close Long") == PositionActionType.CLOSE_LONG
    assert classify_position_action("Open Short") == PositionActionType.OPEN_SHORT
    assert classify_position_action("Close Short") == PositionActionType.CLOSE_SHORT
    assert classify_position_action("mystery") == PositionActionType.UNKNOWN


def test_lifecycle_builder_groups_wallet_coin_actions():
    now = datetime.now(UTC)
    actions = [
        PositionAction("0x" + "a" * 40, "BTC", PositionActionType.OPEN_LONG, now, action_id="a1"),
        PositionAction("0x" + "a" * 40, "BTC", PositionActionType.CLOSE_LONG, now, action_id="a2"),
    ]

    lifecycles = build_lifecycles(actions)

    assert len(lifecycles) == 1
    assert len(lifecycles[0].actions) == 2

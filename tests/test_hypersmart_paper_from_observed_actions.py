from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc

from hyper_smart_observer.hyperliquid_client.models import PositionActionType
from hyper_smart_observer.paper_trading.paper_intent import build_intent_from_observed_action
from hyper_smart_observer.position_lifecycle.lifecycle_models import PositionAction


def test_paper_intent_from_observed_action_is_local_only():
    action = PositionAction(
        action_id="a1",
        wallet_address="0x" + "a" * 40,
        coin="ETH",
        action_type=PositionActionType.OPEN_LONG,
        timestamp=datetime.now(UTC),
        price=100.0,
    )

    intent = build_intent_from_observed_action(action, requested_notional=25.0)

    assert intent.source == "observed_position_action"
    assert "local paper simulation" in intent.reason

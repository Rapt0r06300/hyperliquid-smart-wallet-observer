import pytest

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation
from hyper_smart_observer.explorer_observer.explorer_client import ExplorerClient
from hyper_smart_observer.explorer_observer.explorer_models import ExplorerActionType
from hyper_smart_observer.explorer_observer.explorer_normalization import normalize_explorer_event


def test_explorer_observer_disabled_by_default():
    assert AppConfig().explorer_observer_enabled is False


def test_explorer_client_refuses_network_when_disabled():
    with pytest.raises(SafetyViolation):
        ExplorerClient(AppConfig()).fetch_recent_events(network_read=True)


def test_explorer_normalization_rejects_truncated_wallet():
    event = normalize_explorer_event({"user": "0x1234...abcd", "hash": "tx", "action": "open long"})

    assert event.user is None
    assert event.action_type == ExplorerActionType.OPEN_LONG
    assert any("full wallet" in warning.lower() for warning in event.warnings)

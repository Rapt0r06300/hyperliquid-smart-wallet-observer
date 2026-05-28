import pytest
from hyper_smart_observer.app.config import AppConfig

def test_api_limits_constants():
    config = AppConfig()

    assert config.rest_weight_limit_per_minute == 1200
    assert config.ws_max_connections == 10
    assert config.ws_max_user_subscriptions == 10
    assert config.copy_max_leaders_per_run == 3

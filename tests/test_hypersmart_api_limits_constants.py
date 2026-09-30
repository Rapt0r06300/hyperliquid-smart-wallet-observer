from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.info_client import PaginationResult


def test_api_limit_defaults_are_conservative():
    config = AppConfig()

    assert config.info_time_range_page_limit == 500
    assert config.user_fills_recent_limit == 2000
    assert config.user_fills_by_time_max_recent == 10000
    assert config.rest_weight_limit_per_minute == 1200
    assert config.info_weight_extra_item_bucket_size == 20
    assert config.max_pages_per_wallet == 5
    assert config.max_fills_per_run == 10000
    assert config.ws_max_connections == 10
    assert config.ws_max_new_connections_per_min == 30
    assert config.ws_max_subscriptions == 1000
    assert config.ws_max_user_subscriptions == 10
    assert config.explorer_weight == 40


def test_pagination_result_records_stopped_reason():
    result = PaginationResult(fills=[], pages_fetched=0, stopped_reason="empty_response", warnings=[])

    assert result.stopped_reason == "empty_response"

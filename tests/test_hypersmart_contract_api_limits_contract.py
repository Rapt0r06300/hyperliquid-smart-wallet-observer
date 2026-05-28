import pytest
from hyper_smart_observer.hyperliquid_client.info_client import HyperliquidInfoClient

@pytest.mark.contract
def test_contract_api_limits_constants():
    """
    Contract: API limits constants must be defined and respected.
    """
    # Check if we have constants for limits
    # In hyper_smart_observer, they might be in info_client or config
    from hyper_smart_observer.app.config import AppConfig
    config = AppConfig()

    # Based on mission: HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT=500
    # Let's see if it's there or if we need to tell Codex to add it
    assert hasattr(config, "copy_max_leaders_per_run"), "Contract: Limit on leaders per run must exist"
    assert config.copy_max_leaders_per_run <= 10, "Contract: Safety limit on leaders per run"

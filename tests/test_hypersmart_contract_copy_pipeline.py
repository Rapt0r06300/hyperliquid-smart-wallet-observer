import pytest
import os
import json
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.copy_mode.preflight import run_copy_preflight

@pytest.mark.contract
def test_contract_copy_pipeline_preflight_to_loop():
    """
    Contract test for the full copy pipeline.
    Should ensure preflight and loop functions exist.
    """
    # run_copy_preflight is the entry point for preflight
    assert callable(run_copy_preflight), "run_copy_preflight must be callable"

    # Check for mandatory safety rules
    assert not os.path.exists(".env"), "Safety Contract: .env should not be in project root"

    # run_copy_dry_run is the main entry point for the loop
    assert callable(run_copy_dry_run), "run_copy_dry_run must be callable"

@pytest.mark.contract
def test_contract_copy_pipeline_no_exchange_allowed():
    """
    Contract: The copy pipeline MUST NOT have access to /exchange or private keys.
    """
    from hyper_smart_observer.app.config import AppConfig
    config = AppConfig()
    assert not hasattr(config, "private_key"), "Security Contract: Config must not have private_key"
    assert not hasattr(config, "secret_key"), "Security Contract: Config must not have secret_key"

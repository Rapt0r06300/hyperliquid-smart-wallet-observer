import pytest
from pathlib import Path
from tests.helpers.scenario_runner import ScenarioRunner
from hyper_smart_observer.backtesting.replay_engine import ReplayEngine

@pytest.mark.contract
def test_contract_ultimate_scenario_flow():
    """
    Contract: The simulation must handle the 'Ultimate Cycle' scenario from Entry to Close.
    """
    scenario_path = Path("tests/fixtures/hypersmart/scenario_complex_btc.json")
    runner = ScenarioRunner(scenario_path)
    engine = ReplayEngine()

    # Run through the engine
    report = runner.run_full_cycle(engine.replay_deltas)

    # Verify the results match the sequence length
    assert report.simulated_trades == 4
    assert report.wallet_address == "0x1111111111111111111111111111111111111111"
    # Note: net_pnl is 0.0 because replay_deltas is a stub for Codex
    assert "Stub replay" in report.warnings[0]

@pytest.mark.contract
def test_contract_ledger_integrity():
    """
    Contract: Every observation must be recordable in the ledger.
    """
    import tempfile
    from hyper_smart_observer.storage.research_ledger import ResearchHistoryLedger
    with tempfile.TemporaryDirectory() as tmp_dir:
        ledger = ResearchHistoryLedger(Path(tmp_dir))
        ledger.record_event("TEST_SIGNAL", {"coin": "BTC", "edge": 10.5})

        events = ledger.get_last_n_events(1)
        assert len(events) == 1
        assert events[0]["event_type"] == "TEST_SIGNAL"
        assert events[0]["data"]["coin"] == "BTC"

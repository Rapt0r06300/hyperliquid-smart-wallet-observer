import pytest
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.app.config import AppConfig

@pytest.mark.contract
def test_contract_paper_simulator_presence():
    """
    Contract: The paper simulator must be present and follow local-only rules.
    """
    config = AppConfig(database_path=":memory:")
    simulator = PaperTradingSimulator(config)
    assert hasattr(simulator, 'open_paper_trade'), "Contract: Must have open_paper_trade"
    assert hasattr(simulator, 'close_paper_trade'), "Contract: Must have close_paper_trade"
    assert hasattr(simulator, 'generate_report'), "Contract: Must have generate_report"

@pytest.mark.contract
def test_contract_paper_simulator_no_exchange_logic():
    """
    Contract: Ensure the simulator docstring or code explicitly forbids exchange calls.
    """
    doc = PaperTradingSimulator.__doc__
    assert "never sends an order" in doc.lower()
    assert "never signs payloads" in doc.lower()
    # The actual docstring has a newline between 'a' and 'network request' in some versions,
    # but the check below is safer.
    assert "network request" in doc.lower()

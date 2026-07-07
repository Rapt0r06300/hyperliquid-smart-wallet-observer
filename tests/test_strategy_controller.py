from hl_observer.connectors.paper_execution_connector import LocalPaperExecutionConnector
from hl_observer.connectors.standard import PaperOrderRequest
from hl_observer.strategies.controller import StrategyController, StrategyDecision


def test_strategy_controller_routes_to_paper_execution():
    result = StrategyController(LocalPaperExecutionConnector()).run_once(
        StrategyDecision("wallet_mirror", PaperOrderRequest("HYPE", "LONG", 50))
    )
    assert result.accepted is True
    assert result.paper_only is True

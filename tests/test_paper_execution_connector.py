from hl_observer.connectors.paper_execution_connector import LocalPaperExecutionConnector
from hl_observer.connectors.standard import PaperOrderRequest


def test_paper_execution_connector_rejects_invalid_notional():
    result = LocalPaperExecutionConnector().submit_paper_order(PaperOrderRequest("HYPE", "LONG", 0))
    assert result.accepted is False
    assert result.reason == "INVALID_NOTIONAL"

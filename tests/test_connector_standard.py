from hl_observer.connectors.paper_execution_connector import LocalPaperExecutionConnector
from hl_observer.connectors.standard import PaperOrderRequest


def test_paper_execution_connector_never_real_exchange():
    result = LocalPaperExecutionConnector().submit_paper_order(
        PaperOrderRequest(
            "HYPE",
            "LONG",
            100,
            strategy_id="ext_jack_hl_arbitrage_spread",
            reference_price=70.25,
            metadata={"profile_family": "cross_exchange_arbitrage"},
        )
    )
    assert result.accepted is True
    assert result.order_id.startswith("paper:")
    assert result.real_execution is False
    assert result.strategy_id == "ext_jack_hl_arbitrage_spread"
    assert result.coin == "HYPE"
    assert result.side == "LONG"
    assert result.action == "OPEN"
    assert result.reference_price == 70.25
    assert result.metadata["profile_family"] == "cross_exchange_arbitrage"

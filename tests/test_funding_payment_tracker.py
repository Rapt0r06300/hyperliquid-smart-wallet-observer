from hl_observer.paper_trading.funding_payment_tracker import compute_funding_payment


def test_funding_payment_tracker_returns_paper_pnl():
    payment = compute_funding_payment(coin="HYPE", side="LONG", notional_usdt=1000, funding_rate=0.0001, intervals=2)
    assert payment.coin == "HYPE"
    assert isinstance(payment.pnl_usdt, float)

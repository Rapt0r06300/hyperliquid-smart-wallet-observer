from hl_observer.ops.rapport_simple import rapport_simple


def test_rapport_avec_pnl():
    s = rapport_simple(verdict="MORE_DATA", pnl_net=-5.73, n_trades=96, prochaine_action="collecter plus")
    assert "MORE_DATA" in s and "-5.73 USD" in s and "trades: 96" in s and "collecter plus" in s


def test_pnl_non_mesurable_jamais_zero():
    s = rapport_simple(verdict="NO_GO", pnl_net=None, n_trades=0, prochaine_action="attendre READY")
    assert "UNMEASURABLE" in s and "0.00" not in s

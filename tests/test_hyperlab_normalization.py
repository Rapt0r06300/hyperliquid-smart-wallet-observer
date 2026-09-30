"""[Bloc 34-35] Versioning point-in-time + normalisation cross-venue."""
from hl_observer.hyperlab import normalization as n


def test_symbol_master_pit():
    sm = n.SymbolMasterPiT()
    sm.ajouter_version("BTCUSDT", effective_ts=100, tick=0.1, lot=0.001)
    sm.ajouter_version("BTCUSDT", effective_ts=200, tick=0.5, lot=0.001)
    assert sm.get("BTCUSDT", 150)["tick"] == 0.1     # version effective a t=150
    assert sm.get("BTCUSDT", 250)["tick"] == 0.5
    assert sm.get("BTCUSDT", 50) is None             # aucune spec avant la 1ere version


def test_normalize_ts():
    assert n.normalize_ts(1720000000000) == 1720000000.0   # ms -> s
    assert n.normalize_ts(1720000000) == 1720000000.0      # deja s
    assert abs(n.normalize_ts("2024-07-03T12:26:40+00:00") - 1720009600.0) < 5
    assert n.normalize_ts(None) is None


def test_funding_oi_inverse():
    assert n.funding_to_8h(0.0001, 1) == 0.0008   # 1h -> base 8h
    assert n.funding_to_8h(0.0008, 8) == 0.0008
    assert n.oi_to_notional(1000, 1.0, 60000) == 60000000.0
    assert n.oi_to_notional(1000, None, 60000) is None
    assert n.inverse_contract_notional(10, 100, 60000) == 1000.0


def test_liquidation_side_et_quote():
    # ordre de liq 'sell' (aggressor) => position liquidee 'long'
    assert n.liquidation_side_position("bybit", "sell") == "long"
    assert n.liquidation_side_position("bybit", "buy") == "short"
    q = n.quote_class("USDC", prix_vs_usd=0.985, seuil_depeg=0.01)
    assert q["stable"] and q["classe"] == "usdc" and q["depeg"] is True

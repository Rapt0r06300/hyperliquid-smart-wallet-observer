from hl_observer.research.onchain_metrics import exchange_netflows, whale_flows, regime_open_interest


def test_exchange_netflows():
    mv = [{"direction": "in", "montant": 1000.0}, {"direction": "out", "montant": 300.0}]
    r = exchange_netflows(mv)
    assert r["netflow"] == 700.0 and r["biais"] == "AFFLUX"


def test_whale_flows():
    mv = [{"montant_usd": 2_000_000.0}, {"montant_usd": 5000.0}, {"montant_usd": -1_500_000.0}]
    r = whale_flows(mv)
    assert r["n_whales"] == 2 and r["flux_net_usd"] == 500_000.0


def test_regime_open_interest():
    assert regime_open_interest([100, 130])["regime"] == "EXPANSION"
    assert regime_open_interest([100, 80])["regime"] == "CONTRACTION"
    assert regime_open_interest([100, 102])["regime"] == "STABLE"

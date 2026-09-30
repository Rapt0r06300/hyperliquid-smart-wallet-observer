from hl_observer.research.cex_policy import (
    verifier_cex_public_seulement, marquer_wallet_cex_non_copiable)


def test_cex_public_seulement_refuse_prive():
    ok = ["https://api.binance.com/api/v3/depth", "wss://stream/trades"]
    assert verifier_cex_public_seulement(ok)["public_seulement"] is True
    mixte = ["/api/v3/depth", "/api/v3/order?signed=true"]
    r = verifier_cex_public_seulement(mixte)
    assert r["public_seulement"] is False and len(r["endpoints_prives"]) == 1


def test_wallet_cex_non_copiable():
    assert marquer_wallet_cex_non_copiable({"addr": "0x1", "is_cex": True})["copiable"] is False
    assert marquer_wallet_cex_non_copiable({"addr": "0x2", "type": "leader"})["copiable"] is True

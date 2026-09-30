import os
from hl_observer.collection.collector import CollectionPlan, _maybe_apply_ws_first


def _p():
    return CollectionPlan(wallets=["0x" + "a" * 40], all_mids=True, user_fills=True, open_orders=True)


def test_off_is_noop(monkeypatch):
    monkeypatch.delenv("HYPERSMART_WS_FIRST_COLLECT", raising=False)
    p = _maybe_apply_ws_first(_p())
    assert p.all_mids and p.user_fills and p.open_orders     # rien change


def test_on_drops_ws_covered(monkeypatch):
    monkeypatch.setenv("HYPERSMART_WS_FIRST_COLLECT", "1")
    monkeypatch.setenv("HYPERSMART_WS_FIRST_CHANNELS", "allMids,userFills")
    p = _maybe_apply_ws_first(_p())
    assert p.all_mids is False and p.user_fills is False     # WS couvre -> REST coupe
    assert p.open_orders is True                              # non couvert -> garde

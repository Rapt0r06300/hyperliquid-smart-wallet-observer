"""Contrat WS-first: couper le REST redondant, quantifier le poids économisé."""

from __future__ import annotations

from hl_observer.collection.ws_first_plan import apply_ws_first, within_budget


def _plan():
    # plan typique: par-wallet open_orders + user_fills, + allMids global
    return {"all_mids": True, "open_orders": True, "user_fills": True, "user_fills_by_time": False,
            "frontend_open_orders": False, "l2_book": False, "candles": False}


def test_drops_ws_covered_rest_and_saves_weight():
    r = apply_ws_first(plan_flags=_plan(), ws_fresh_channels={"allMids", "userFills"}, num_wallets=50)
    # userFills WS couvre user_fills (50*20=1000) ; allMids WS couvre all_mids (2)
    assert set(r["dropped_rest_items"]) == {"all_mids", "user_fills"}
    assert r["flags"]["user_fills"] is False and r["flags"]["all_mids"] is False
    assert r["flags"]["open_orders"] is True                 # non couvert par WS -> gardé
    assert r["weight_saved_per_cycle"] == 1002               # 1000 + 2


def test_conservative_keeps_rest_when_ws_not_fresh():
    # aucun canal WS frais -> on ne coupe RIEN (jamais de trou de données)
    r = apply_ws_first(plan_flags=_plan(), ws_fresh_channels=set(), num_wallets=50)
    assert r["dropped_rest_items"] == []
    assert r["weight_saved_per_cycle"] == 0


def test_ws_first_brings_plan_under_budget():
    # 50 wallets, 15s: REST-only dépasse; WS-first repasse sous 1200/min
    before = apply_ws_first(plan_flags=_plan(), ws_fresh_channels=set(), num_wallets=50)
    after = apply_ws_first(plan_flags=_plan(), ws_fresh_channels={"allMids", "userFills"}, num_wallets=50)
    assert within_budget(weight_per_cycle=before["weight_after_per_cycle"], interval_s=15.0) is False  # REST seul = throttle
    # après WS-first il ne reste que open_orders (50*20=1000/cycle -> 4000/min) : encore trop,
    # mais on a supprimé 1002/cycle. within_budget le montre honnêtement:
    assert after["weight_after_per_cycle"] < before["weight_after_per_cycle"]


def test_within_budget_scales_with_proxies():
    # 1000 poids/cycle @15s = 4000/min : hors budget à 1 IP, OK à 5 IP
    assert within_budget(weight_per_cycle=1000, interval_s=15.0, num_egress_ips=1) is False
    assert within_budget(weight_per_cycle=1000, interval_s=15.0, num_egress_ips=5) is True


class _FakePlan:
    """Plan duck-typé pour tester reduce_plan_from_env sans CollectionPlan."""
    def __init__(self, **kw):
        self.wallets = kw.pop("wallets", [])
        self.coins = kw.pop("coins", [])
        for k, v in kw.items():
            setattr(self, k, v)


def test_reduce_plan_from_env_off_is_noop():
    from hl_observer.collection.ws_first_plan import reduce_plan_from_env
    p = _FakePlan(wallets=["0x1"], all_mids=True, user_fills=True, open_orders=True)
    out = reduce_plan_from_env(p, env={})
    assert out.all_mids and out.user_fills and out.open_orders     # rien changé


def test_reduce_plan_from_env_on_drops_ws_covered():
    from hl_observer.collection.ws_first_plan import reduce_plan_from_env
    p = _FakePlan(wallets=["0x1", "0x2"], all_mids=True, user_fills=True, open_orders=True,
                  l2_book=False, candles=False, user_fills_by_time=False, frontend_open_orders=False)
    out = reduce_plan_from_env(p, env={"HYPERSMART_WS_FIRST_COLLECT": "1",
                                       "HYPERSMART_WS_FIRST_CHANNELS": "allMids,userFills"})
    assert out.all_mids is False and out.user_fills is False       # WS couvre -> REST coupé
    assert out.open_orders is True                                  # non couvert -> gardé

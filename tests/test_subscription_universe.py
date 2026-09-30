"""P3.4 v2 — Universe Manager : vraies subscriptions HL, quotas 1000/10/10, subscribe/unsubscribe dynamique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import subscription_universe as U  # noqa: E402


def test_priorite_positions_avant_le_reste():
    u = U.construire_univers(positions_ouvertes=["BTC"], twap_actifs=["ETH"],
                             candidats_anticipation=["SOL"], cross_venue_liquides=["INJ"])
    assert [c["coin"] for c in u["coins"]] == ["BTC", "ETH", "SOL", "INJ"]


def test_accounting_compte_les_vraies_subscriptions():
    # 2 coins × (bbo+l2Book+trades)=6, 2 users × (userFills+userTwapSliceFills)=4, +1 allMids = 11.
    u = U.construire_univers(positions_ouvertes=["BTC", "ETH"], core_wallets=["w1", "w2"])
    acc = u["accounting"]
    assert acc["subscriptions_coins"] == 6 and acc["subscriptions_users"] == 4
    assert acc["subscriptions_globales"] == 1 and acc["subscriptions_totales"] == 11
    assert acc["subscriptions_ok"] and acc["users_ok"] and acc["connexions_ok"]
    assert u["coins"][0]["streams"] == list(U.STREAMS_COIN_DEFAUT)


def test_quota_subscriptions_borne_les_coins_pas_seulement_les_coins():
    # budget = 5 − 0 user − 1 global = 4 ; 2 subs/coin → 2 coins max ; 3 abandonnés nommément.
    u = U.construire_univers(cross_venue_liquides=["A", "B", "C", "D", "E"],
                             streams_coin=("bbo", "l2Book"), quota_subscriptions=5)
    assert [c["coin"] for c in u["coins"]] == ["A", "B"]
    assert [c["coin"] for c in u["abandons"]["coins"]] == ["C", "D", "E"]
    assert u["accounting"]["subscriptions_totales"] == 5 and u["accounting"]["subscriptions_ok"]


def test_users_8_core_2_challengers_et_subs_user():
    u = U.construire_univers(core_wallets=[f"c{i}" for i in range(10)],
                             challengers=[f"h{i}" for i in range(5)])
    assert len(u["users_core"]) == 8 and len(u["users_challengers"]) == 2
    assert u["accounting"]["users_uniques"] == 10
    assert u["accounting"]["subscriptions_users"] == 10 * 2      # 10 users × 2 streams


def test_connexions_estimees_respecte_le_quota():
    # 300 coins × 3 = 900 subs + 1 allMids = 901 → 10 connexions (à 100/conn), pile au quota.
    u = U.construire_univers(cross_venue_liquides=[f"C{i}" for i in range(300)], subs_par_connexion=100)
    acc = u["accounting"]
    assert acc["subscriptions_coins"] == 900 and acc["subscriptions_totales"] == 901
    assert acc["connexions_estimees"] == 10 and acc["connexions_ok"] is True


def test_diff_souscriptions_dynamique():
    ancien = U.construire_univers(positions_ouvertes=["A", "B"], streams_coin=("bbo",))
    nouveau = U.construire_univers(positions_ouvertes=["B", "C"], streams_coin=("bbo",))
    d = U.diff_souscriptions(ancien, nouveau)
    assert "bbo:C" in d["a_souscrire"] and "bbo:A" in d["a_desouscrire"]
    assert "bbo:B" not in d["a_souscrire"] and "bbo:B" not in d["a_desouscrire"]


def test_diff_depuis_rien_souscrit_tout():
    nouveau = U.construire_univers(positions_ouvertes=["A"], core_wallets=["w1"])
    d = U.diff_souscriptions(None, nouveau)
    assert "allMids:*" in d["a_souscrire"] and "userFills:w1" in d["a_souscrire"]
    assert d["a_desouscrire"] == []


def test_univers_vide():
    u = U.construire_univers()
    assert u["coins"] == [] and u["accounting"]["subscriptions_totales"] == 1   # juste allMids

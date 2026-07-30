"""P3.4 — Subscription Universe Manager : priorité, dédup, quotas, abandons nommés."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import subscription_universe as U  # noqa: E402


def test_priorite_positions_avant_le_reste():
    u = U.construire_univers(
        positions_ouvertes=["BTC"], twap_actifs=["ETH"],
        candidats_anticipation=["SOL"], cross_venue_liquides=["INJ"],
    )
    coins = [c["coin"] for c in u["coins"]]
    assert coins == ["BTC", "ETH", "SOL", "INJ"]
    assert u["coins"][0]["priorite"] == "positions_ouvertes"


def test_dedup_garde_la_priorite_la_plus_haute():
    u = U.construire_univers(positions_ouvertes=["BTC"], cross_venue_liquides=["BTC", "ETH"])
    coins = {c["coin"]: c["priorite"] for c in u["coins"]}
    assert coins["BTC"] == "positions_ouvertes"      # pas cross_venue
    assert coins["ETH"] == "cross_venue_liquides"
    assert len(u["coins"]) == 2


def test_accepte_les_dicts_avec_coin():
    u = U.construire_univers(positions_ouvertes=[{"coin": "btc"}], twap_actifs=[{"coin": "eth"}])
    assert [c["coin"] for c in u["coins"]] == ["BTC", "ETH"]


def test_quota_coins_abandonne_le_surplus_nomme():
    u = U.construire_univers(cross_venue_liquides=["A", "B", "C", "D"], quota_coins=2)
    assert [c["coin"] for c in u["coins"]] == ["A", "B"]
    assert [c["coin"] for c in u["abandons"]["coins"]] == ["C", "D"]     # pas coupé en silence


def test_user_slots_8_core_2_challengers():
    core = [f"c{i}" for i in range(10)]        # 10 CORE proposés
    chall = [f"h{i}" for i in range(5)]        # 5 challengers proposés
    u = U.construire_univers(core_wallets=core, challengers=chall)
    assert len(u["users_core"]) == 8 and len(u["users_challengers"]) == 2
    assert u["quotas"]["user_slots_utilises"] == 10
    assert u["abandons"]["users"]["core"] == ["c8", "c9"]
    assert u["abandons"]["users"]["challengers"] == ["h2", "h3", "h4"]


def test_un_core_nest_pas_aussi_challenger():
    u = U.construire_univers(core_wallets=["w1", "w2"], challengers=["w1", "w3"])
    assert u["users_core"] == ["w1", "w2"] and u["users_challengers"] == ["w3"]


def test_challengers_reduits_si_core_remplit_le_quota_global():
    core = [f"c{i}" for i in range(9)]        # 9 CORE mais core_slots=8 → 8 pris
    u = U.construire_univers(core_wallets=core, challengers=["h1", "h2"], quota_user_slots=9)
    # 8 CORE + reste 1 slot global → 1 challenger seulement
    assert len(u["users_core"]) == 8 and len(u["users_challengers"]) == 1


def test_univers_vide():
    u = U.construire_univers()
    assert u["coins"] == [] and u["users_core"] == [] and u["real_execution"] is False

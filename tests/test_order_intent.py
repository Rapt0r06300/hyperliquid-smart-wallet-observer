"""ALPHA — L4/order-intent : reconstruction cycle, features (chase/escalation/fill), agrégats, BLOCKED sans flux."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import order_intent as O  # noqa: E402


def _cycle_buy_chase_fill():
    # un ordre BUY qui CHASSE le prix vers le haut puis est rempli
    return [
        {"order_id": "o1", "ts_ms": 0, "type": "NEW", "side": "BUY", "px": 100.0, "sz": 1.0, "mid": 100.5},
        {"order_id": "o1", "ts_ms": 1000, "type": "MODIFY", "side": "BUY", "px": 100.3, "sz": 2.0, "mid": 100.5},
        {"order_id": "o1", "ts_ms": 2000, "type": "FILL", "side": "BUY", "px": 100.5, "sz": 2.0, "mid": 100.5},
    ]


def test_reconstruit_et_trie():
    ev = list(reversed(_cycle_buy_chase_fill()))
    cyc = O.reconstruire_cycles(ev)
    assert list(cyc) == ["o1"] and cyc["o1"][0]["type"] == "NEW"


def test_cycle_features():
    f = O.cycle_features(_cycle_buy_chase_fill())
    assert f["eventual_fill"] is True and f["n_modify"] == 1
    assert f["size_escalation"] == 2.0                     # 1 -> 2
    assert f["chase_velocity_bps_s"] > 0                   # BUY qui monte vers le touch
    assert f["persistence_ms"] == 2000


def test_agreger_wallet_ratios():
    cycles = {
        "o1": _cycle_buy_chase_fill(),                                            # fill + modify
        "o2": [{"order_id": "o2", "ts_ms": 0, "type": "NEW", "side": "SELL", "px": 101.0, "sz": 1.0},
               {"order_id": "o2", "ts_ms": 500, "type": "CANCEL", "side": "SELL", "px": 101.0, "sz": 1.0}],
    }
    a = O.agreger_wallet(cycles)
    assert a["fill_ratio"] == 0.5 and a["cancel_ratio"] == 0.5 and a["replace_ratio"] == 0.5


def test_experience_blocked_sans_flux():
    r = O.experience_intent(None)
    assert r["verdict"] == O.BLOCKED and "FILL_ONLY" in r["tests_prevus"]


def test_experience_mesurable_si_flux():
    r = O.experience_intent(_cycle_buy_chase_fill())
    assert r["verdict"] == "MEASURABLE" and r["n_cycles"] == 1


def test_recherche_l4_ignore_les_evenements_invalides_sans_nan_ou_tri_ambigu():
    events = _cycle_buy_chase_fill() + [
        {"order_id": "bad", "ts_ms": float("nan"), "type": "FILL", "px": 1.0, "sz": 1.0},
        {"order_id": "bad", "ts_ms": "later", "type": "FILL", "px": 1.0, "sz": 1.0},
        {"order_id": "bad", "ts_ms": 2, "type": "UNKNOWN", "px": 1.0, "sz": 1.0},
    ]
    cycles = O.reconstruire_cycles(events)
    assert list(cycles) == ["o1"]
    assert O.cycle_features([{"type": "FILL", "ts_ms": float("nan"), "px": float("inf"), "sz": -1.0}])["persistence_ms"] == 0.0

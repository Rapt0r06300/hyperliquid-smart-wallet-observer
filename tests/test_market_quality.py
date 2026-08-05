from hl_observer.research.market_quality import (
    classer_regime_options, filtrer_manipulation, pannes_correlees, detecter_changement_api)


def test_classer_regime_options():
    assert classer_regime_options(iv_atm=0.3, skew_25d=-0.01)["regime"] == "CALME"
    assert classer_regime_options(iv_atm=0.6, skew_25d=-0.02)["regime"] == "STRESSE"
    assert classer_regime_options(iv_atm=0.9, skew_25d=-0.2)["regime"] == "PANIQUE"


def test_filtrer_manipulation():
    quotes = [{"px": 100, "annule_apres_ms": 10}, {"px": 101, "annule_apres_ms": None}, {"px": 102, "annule_apres_ms": 500}]
    r = filtrer_manipulation(quotes)
    assert r["suspects"] == [0] and len(r["propres"]) == 2


def test_pannes_correlees():
    assert pannes_correlees({"a": "DOWN", "b": "DOWN", "c": "OK"})["panne_correlee"] is True
    assert pannes_correlees({"a": "DOWN", "b": "OK", "c": "OK", "d": "OK"})["panne_correlee"] is False


def test_detecter_changement_api():
    r = detecter_changement_api({"px": "float", "sz": "float"}, {"px": "str", "sz": "float", "extra": "int"})
    assert r["a_change"] is True and r["apparus"] == ["extra"] and r["types_changes"] == ["px"]

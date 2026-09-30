"""[ARB #13] minimum-notional preflight : une jambe sous le notional min de sa venue invalide l'arb complet."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import minimum_notional_preflight as MNP   # noqa: E402


def test_deux_jambes_valides():
    jambes = {"HL": {"prix": 100.0, "taille": 0.2}, "BINANCE": {"prix": 100.0, "taille": 0.2}}
    r = MNP.preflight_min_notional(jambes, min_notional_par_venue={"HL": 10.0, "BINANCE": 10.0})
    assert r["ok"] is True and r["invalides"] == []


def test_une_jambe_sous_le_minimum_rejette_tout():
    jambes = {"HL": {"prix": 100.0, "taille": 0.2}, "BINANCE": {"prix": 100.0, "taille": 0.05}}
    r = MNP.preflight_min_notional(jambes, min_notional_par_venue={"HL": 10.0, "BINANCE": 10.0})
    assert r["ok"] is False and r["invalides"] == ["BINANCE"]   # 5$ < 10$


def test_minimum_inconnu_invalide_jamais_suppose_ok():
    jambes = {"HL": {"prix": 100.0, "taille": 0.2}, "BINANCE": {"prix": 100.0, "taille": 0.2}}
    r = MNP.preflight_min_notional(jambes, min_notional_par_venue={"HL": 10.0})
    assert r["ok"] is False and "BINANCE" in r["invalides"]     # minimum manquant = invalide

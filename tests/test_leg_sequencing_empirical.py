"""[ARB #45] leg sequencing empirique : la jambe la plus incertaine (venue la moins fiable) s'exécute d'abord."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.leg_sequencing_empirical import ordonner_jambes   # noqa: E402


def test_venue_la_plus_risquee_en_premier():
    r = ordonner_jambes("HL", {"proba_echec": 0.02, "latence_ms": 40.0},
                        "BINANCE", {"proba_echec": 0.10, "latence_ms": 80.0})
    assert r["premiere"] == "BINANCE" and r["seconde"] == "HL"       # BINANCE plus risquée -> d'abord


def test_departage_par_latence():
    r = ordonner_jambes("A", {"proba_echec": 0.05, "latence_ms": 30.0},
                        "B", {"proba_echec": 0.05, "latence_ms": 90.0})
    assert r["premiere"] == "B"                                      # même proba, B plus lente -> d'abord


def test_stats_manquantes_non_mesurable():
    r = ordonner_jambes("A", {"latence_ms": 30.0}, "B", {"proba_echec": 0.05})
    assert r["ordre"] == "UNMEASURABLE"

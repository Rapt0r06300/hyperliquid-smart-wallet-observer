"""ALPHA P12 — recette economique : 4 scenarios, OPTIMISTIC ne promeut jamais, survie ADVERSE_P95."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import recette_economique as R  # noqa: E402


def test_optimistic_ne_promeut_jamais():
    assert R.peut_promote("OPTIMISTIC_DIAGNOSTIC_ONLY") is False
    assert R.peut_promote("ADVERSE_P95") is True
    assert R.verdict_bloque_si_optimiste("OPTIMISTIC_DIAGNOSTIC_ONLY", "PROMOTE") == "MORE_DATA"


def test_adverse_plus_cher_que_base():
    base = R.net_sous_scenario(30.0, 9.0, "BASE_CALIBRATED")
    p99 = R.net_sous_scenario(30.0, 9.0, "ADVERSE_P99")
    assert p99 < base                                       # plus adverse -> net plus faible


def test_evaluer_recette_promote_si_survit_adverse():
    r = R.evaluer_recette(30.0, 9.0)                        # gross 30, cout 9 -> survit p95
    assert r["verdict"] == "PROMOTE" and r["promote_si_adverse_p95"] is True
    r2 = R.evaluer_recette(10.0, 9.0)                       # survit base mais pas forcement adverse
    assert r2["verdict"] in ("MORE_DATA", "KILL", "PROMOTE")
    r3 = R.evaluer_recette(5.0, 9.0)                        # net base negatif -> KILL
    assert r3["verdict"] == "KILL"

"""ALPHA — exécution maker queue-aware : taker mesurable, maker UNMEASURABLE sans trades, matrice."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import execution_maker as E  # noqa: E402


def test_cout_taker():
    assert E.cout_taker_bps(1.0, fees_bps=9.0) == 10.0


def test_taker_net_mesurable():
    r = E.evaluer_execution(12.0, mode="TAKER", spread_bps=1.0)
    assert r["statut"] == "MEASURABLE" and r["net_bps"] == 2.0        # 12 - (9+1)


def test_maker_unmeasurable_sans_volume():
    r = E.evaluer_execution(12.0, mode="MAKER", spread_bps=4.0, taille_devant=100.0)
    assert r["statut"] == "UNMEASURABLE" and r["net_bps"] == E.UNMEASURABLE
    assert r["proba_fill"] is None


def test_maker_mesurable_avec_volume_et_adverse():
    r = E.evaluer_execution(12.0, mode="MAKER", spread_bps=4.0, taille_devant=50.0,
                            notre_taille=50.0, volume_traversant=100.0, adverse_selection_bps=3.0)
    assert r["statut"] == "MEASURABLE" and r["proba_fill"] == 1.0
    assert r["net_bps"] == r["net_si_fill_bps"]


def test_proba_fill_bornee_et_queue():
    assert E.proba_fill_maker(1000.0, 10.0, 1.0) < 0.02
    assert E.position_file_attente(0.0, 1.0) == 0.0
    assert 0.0 < E.position_file_attente(9.0, 1.0) < 1.0


def test_matrice_maker_maker_unmeasurable_sans_preuve_queue():
    m = E.evaluer_matrice(12.0, spread_bps=2.0)
    assert m["TAKER/TAKER"]["statut"] == "MEASURABLE"
    assert m["MAKER/MAKER"]["statut"] == "UNMEASURABLE"

"""[LAB α] lab_eta : calibration → estimation honnête, format HH:MM:SS, progrès."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.lab_eta import MoteurETA, format_hms   # noqa: E402


def test_calibration_puis_estimation():
    e = MoteurETA(total_etapes=10, min_echantillons=3)
    e.terminer_etape(2.0)
    e.terminer_etape(2.0)
    assert e.estimer(elapsed_s=4.0)["calibration"] is True and \
        e.estimer(elapsed_s=4.0)["texte"] == "ETA EN CALIBRATION"
    e.terminer_etape(2.0)
    est = e.estimer(elapsed_s=6.0)
    assert est["calibration"] is False and est["eta_total_s"] == 14.0 and est["texte"].startswith("ETA 00:")


def test_format_hms():
    assert format_hms(3661) == "01:01:01" and format_hms(-5) == "00:00:00"


def test_progres():
    e = MoteurETA(total_etapes=4)
    e.terminer_etape(1.0, octets=100, evenements=5)
    p = e.progres()
    assert p["etapes_finies"] == 1 and p["pct"] == 25.0 and p["octets_traites"] == 100


def test_debit_reel_et_intervalle_incertitude_item15():
    from hl_observer.ops.lab_eta import MoteurETA
    m = MoteurETA(total_etapes=10, min_echantillons=3)
    for _ in range(4):
        m.terminer_etape(2.0, octets=1000, evenements=500)
    est = m.estimer(elapsed_s=8.0)
    # debit REEL observe (evenements/s, octets/s)
    assert est["debit_evenements_s"] == round(2000 / 8.0, 3)      # 4*500 events / 8 s
    assert est["debit_octets_s"] == round(4000 / 8.0, 1)
    # duree PROPRE de la derniere etape (pas un cumul)
    assert est["derniere_duree_s"] == 2.0
    # intervalle d'incertitude explicite [bas, haut] encadrant l'ETA
    assert est["eta_bas_s"] <= est["eta_total_s"] <= est["eta_haut_s"]


def test_eta_en_calibration_expose_deja_le_debit():
    from hl_observer.ops.lab_eta import MoteurETA
    m = MoteurETA(total_etapes=10, min_echantillons=5)
    m.terminer_etape(1.0, evenements=100)
    est = m.estimer(elapsed_s=1.0)
    assert est["calibration"] is True and est["texte"] == "ETA EN CALIBRATION"
    assert est["debit_evenements_s"] == 100.0                     # le debit est visible des la calibration

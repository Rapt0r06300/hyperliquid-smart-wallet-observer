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

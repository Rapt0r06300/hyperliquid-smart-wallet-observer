"""[pépite 275] writer-lag budget : event_received → durable_write ; disque trop lent → capture dégradée."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.capture.writer_lag_budget import evaluer   # noqa: E402


def test_lag_dans_budget():
    r = evaluer(1000.0, 1100.0, budget_ms=250.0)   # lag 100ms
    assert r["etat"] == "OK" and r["lag_ms"] == 100.0


def test_lag_hors_budget_degrade():
    r = evaluer(1000.0, 1400.0, budget_ms=250.0)   # lag 400ms
    assert r["etat"] == "DEGRADE" and r["raison"] == "BUDGET_DEPASSE"


def test_lag_negatif_et_invalide():
    assert evaluer(1000.0, 900.0)["raison"] == "LAG_NEGATIF"
    assert evaluer(None, 1000.0)["etat"] == "DEGRADE"

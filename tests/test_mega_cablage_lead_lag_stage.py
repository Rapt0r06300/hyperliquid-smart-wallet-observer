"""[CABLAGE Lead-Lag] lead_lag_stage : la direction leader précède-t-elle le move du mid ?"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.lead_lag_stage import score_lead_lag   # noqa: E402


def test_leader_predictif():
    paires = [(1, +2.0), (1, +1.0), (-1, -2.0), (-1, -1.0)] * 6   # signe aligné au move -> prédictif
    r = score_lead_lag(paires, min_echantillons=20)
    assert r["score"] == 1.0 and r["predictif"] is True and r["edge_bps_moyen"] > 0


def test_leader_anti_predictif():
    paires = [(1, -2.0), (-1, +2.0)] * 12                          # systématiquement à contre-sens
    r = score_lead_lag(paires, min_echantillons=20)
    assert r["score"] == 0.0 and r["predictif"] is False


def test_echantillon_insuffisant_unmeasurable():
    assert score_lead_lag([(1, 1.0)], min_echantillons=20)["score"] == "UNMEASURABLE"

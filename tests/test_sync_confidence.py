"""[COPY-VAULT lot2 #39] sync_confidence : score [0,1] pénalisé par gaps, désaccord REST/WS, état vieux."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.sync_confidence import score   # noqa: E402


def test_parfait():
    r = score(gaps=0, rest_ws_accord=True, age_etat_ms=0.0, position_reconstruite_ok=True)
    assert r["sync_confidence"] == 1.0


def test_penalise_par_defauts():
    r = score(gaps=1, rest_ws_accord=False, age_etat_ms=0.0, position_reconstruite_ok=True)
    assert r["sync_confidence"] < 1.0 and "gaps" in r["penalites"] and "rest_ws_desaccord" in r["penalites"]


def test_borne_a_zero():
    r = score(gaps=5, rest_ws_accord=False, age_etat_ms=999999.0, position_reconstruite_ok=False)
    assert r["sync_confidence"] == 0.0


def test_observations_absentes_refusent_l_ouverture():
    r = score()
    assert r["state"] == "UNMEASURABLE"
    assert r["refuse"] is True
    assert r["sync_confidence"] is None


def test_nan_et_age_negatif_sont_refuses():
    complete = dict(gaps=0, rest_ws_accord=True, position_reconstruite_ok=True)
    assert score(**complete, age_etat_ms=float("nan"))["refuse"] is True
    assert score(**complete, age_etat_ms=-1.0)["refuse"] is True


def test_bool_et_gaps_invalides_sont_refuses():
    assert score(gaps=True, rest_ws_accord=True, age_etat_ms=0.0,
                 position_reconstruite_ok=True)["refuse"] is True
    assert score(gaps=float("nan"), rest_ws_accord=True, age_etat_ms=0.0,
                 position_reconstruite_ok=True)["refuse"] is True
    assert score(gaps=float("inf"), rest_ws_accord=True, age_etat_ms=0.0,
                 position_reconstruite_ok=True)["refuse"] is True
    assert score(gaps=0, rest_ws_accord=1, age_etat_ms=0.0,
                 position_reconstruite_ok=True)["refuse"] is True

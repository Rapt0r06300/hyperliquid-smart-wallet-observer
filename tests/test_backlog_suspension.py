"""[COPY-VAULT lot2 #49] suspension si backlog > cadence : arrivée plus rapide que traitement -> suspension."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.backlog_suspension import doit_suspendre   # noqa: E402


def test_cadence_tenable():
    r = doit_suspendre(taux_arrivee_par_s=5.0, taux_traitement_par_s=10.0)
    assert r["suspendre"] is False


def test_arrivee_trop_rapide():
    r = doit_suspendre(taux_arrivee_par_s=20.0, taux_traitement_par_s=10.0)
    assert r["suspendre"] is True and r["raison"] == "ARRIVEE_PLUS_RAPIDE_QUE_TRAITEMENT"


def test_backlog_max_depasse():
    r = doit_suspendre(taux_arrivee_par_s=1.0, taux_traitement_par_s=10.0, backlog=100, backlog_max=50)
    assert r["suspendre"] is True and r["raison"] == "BACKLOG_MAX_DEPASSE"

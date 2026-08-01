"""[LAB α] lab_audit : statut par brique du chemin canonique (import réel × disponibilité des données)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.lab_audit import auditer, CABLE_UTILISE, CABLE_SANS_DONNEE   # noqa: E402


def test_tout_cable_et_utilise_avec_donnees():
    r = auditer(a_des_evenements=True, a_des_carnets_hedge=True, a_lead_lag=True)
    assert r["resume"][CABLE_UTILISE] == 8 and len(r["bricks"]) == 8


def test_sans_donnees_les_bricks_data_sont_sans_donnee():
    r = auditer(a_des_evenements=False, a_des_carnets_hedge=False, a_lead_lag=False)
    par_nom = {b["brique"]: b["statut"] for b in r["bricks"]}
    assert par_nom["feed_adapter"] == CABLE_SANS_DONNEE and par_nom["Cross-Venue"] == CABLE_SANS_DONNEE
    assert par_nom["MegaCablage"] == CABLE_UTILISE           # spine toujours utilisée


def test_resume_couvre_tous_les_statuts():
    r = auditer(a_des_evenements=True)
    assert set(r["resume"]) >= {CABLE_UTILISE, CABLE_SANS_DONNEE, "BLOQUE", "ERREUR"}

"""AUD-001 / AUD-073 — PROVENANCE DENY-BY-DEFAULT.

Une absence d'attestation de provenance n'est PAS une preuve de donnee reelle. Le catalogue de session
ne retombe JAMAIS sur REEL par defaut : defaut, valeur invalide ou catalogue muet -> UNKNOWN. Seul le
vrai collecteur de production (session_harvest) atteste REEL ; une fixture atteste SYNTHETIQUE.
0 reseau, 0 ordre.
"""
from __future__ import annotations

import json
import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import session_catalog as SC              # noqa: E402
from hl_observer.ops import session_harvest as SH              # noqa: E402
from hl_observer.ops.session_catalog import CatalogueSession   # noqa: E402


def test_demarrer_sans_attestation_est_UNKNOWN_pas_REEL(tmp_path):
    cat = CatalogueSession(tmp_path, "run-x").demarrer(horloge=lambda: 1000.0)
    assert cat["data_origin"] == SC.ORIGINE_INCONNUE
    assert cat["data_origin"] != SC.ORIGINE_REEL


def test_data_origin_invalide_retombe_sur_UNKNOWN_pas_REEL(tmp_path):
    cat = CatalogueSession(tmp_path, "run-y").demarrer(data_origin="N_IMPORTE_QUOI", horloge=lambda: 1000.0)
    assert cat["data_origin"] == SC.ORIGINE_INCONNUE


def test_attestation_reelle_positive_est_conservee(tmp_path):
    cat = CatalogueSession(tmp_path, "run-r").demarrer(data_origin=SC.ORIGINE_REEL, horloge=lambda: 1000.0)
    assert cat["data_origin"] == SC.ORIGINE_REEL


def test_fixture_synthetique_est_conservee(tmp_path):
    cat = CatalogueSession(tmp_path, "run-s").demarrer(data_origin=SC.ORIGINE_SYNTHETIQUE, horloge=lambda: 1000.0)
    assert cat["data_origin"] == SC.ORIGINE_SYNTHETIQUE


def test_scanner_catalogue_muet_est_UNKNOWN_pas_REEL(tmp_path):
    d = SC.chemin_session(tmp_path, "run-muet")
    d.mkdir(parents=True, exist_ok=True)
    (d / SC.NOM_CATALOGUE).write_text(json.dumps(
        {"run_id": "run-muet", "statut": SC.STATUT_COMPLETE, "debut_ms": 1000}), encoding="utf-8")
    s = next(x for x in SC.scanner_sessions(tmp_path) if x["run_id"] == "run-muet")
    assert s["data_origin"] == SC.ORIGINE_INCONNUE


def test_harvest_atteste_REEL(tmp_path):
    rid, cat = SH.ouvrir_session_harvest(tmp_path, horloge=lambda: 1000.0)
    assert cat["data_origin"] == SC.ORIGINE_REEL


def test_helper_origine_prouvee_reelle():
    assert SC.origine_prouvee_reelle(SC.ORIGINE_REEL) is True
    assert SC.origine_prouvee_reelle(SC.ORIGINE_INCONNUE) is False
    assert SC.origine_prouvee_reelle(SC.ORIGINE_SYNTHETIQUE) is False
    assert SC.origine_prouvee_reelle({"data_origin": SC.ORIGINE_REEL}) is True
    assert SC.origine_prouvee_reelle({"data_origin": SC.ORIGINE_INCONNUE}) is False
    assert SC.origine_prouvee_reelle(None) is False


def test_cliquet_le_defaut_reste_UNKNOWN():
    sig = inspect.signature(CatalogueSession.demarrer)
    assert sig.parameters["data_origin"].default == SC.ORIGINE_INCONNUE
    assert SC.ORIGINE_INCONNUE in SC.ORIGINES

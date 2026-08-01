"""[pépite 257] fixed-point serialization contract : le format disque ne réintroduit jamais de float."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.data_contract.fixed_point_serialization_contract import verifier_contrat   # noqa: E402


def test_str_et_int_conformes():
    rec = {"price": "100.25", "qty": 1050000}     # str + int scalé
    assert verifier_contrat(rec, ["price", "qty"])["conforme"] is True


def test_float_interdit():
    rec = {"price": 100.25, "qty": "1.0"}
    r = verifier_contrat(rec, ["price", "qty"])
    assert r["etat"] == "VIOLATION" and r["violations"][0]["raison"] == "FLOAT_INTERDIT"


def test_champ_absent():
    r = verifier_contrat({"price": "1"}, ["price", "qty"])
    assert any(v["raison"] == "CHAMP_ABSENT" for v in r["violations"])

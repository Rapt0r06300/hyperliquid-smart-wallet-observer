"""[pépite 266] adapter conformance suite : tous les connecteurs satisfont les mêmes invariants."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.data_contract.adapter_conformance_suite import verifier_conformite   # noqa: E402


def test_evenement_conforme():
    ev = {"price": 100.0, "qty": 1.0, "side": "BUY", "ts": 1_700_000_000_000}
    assert verifier_conformite(ev)["conforme"] is True


def test_violations_multiples():
    ev = {"price": -1.0, "qty": 0.0, "side": "HOLD", "ts": 0}
    r = verifier_conformite(ev)
    assert r["etat"] == "NON_CONFORME" and set(r["violations"]) == {"PRICE", "QTY", "SIDE", "TS"}


def test_sequence_exigee():
    ev = {"price": 100.0, "qty": 1.0, "side": "SELL", "ts": 1_700_000_000_000}
    assert verifier_conformite(ev, exige_sequence=True)["violations"] == ["SEQUENCE"]

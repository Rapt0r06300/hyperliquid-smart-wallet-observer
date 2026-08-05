"""AUD-033..040 — disposition REJECTED (spec irrecuperable) formellement enregistree et reouvrable."""
from __future__ import annotations
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DOC = (RACINE / "docs" / "audit" / "AUD_033_040_DISPOSITION.md").read_text(encoding="utf-8")


def test_les_8_ids_sont_tous_dispositionnes():
    for n in range(33, 41):
        assert ("AUD-0%d" % n) in DOC, "AUD-0%d absent de la disposition" % n


def test_verdict_rejected_spec_irrecuperable():
    assert "REJECTED" in DOC and "irrecuperable" in DOC.lower()


def test_condition_de_reouverture_documentee():
    assert "MASTER V3" in DOC and "rouvre" in DOC.lower()


def test_ne_pretend_jamais_un_correctif():
    bas = DOC.lower()
    assert "aucun correctif n'est invente" in bas and "pas marques done" in bas

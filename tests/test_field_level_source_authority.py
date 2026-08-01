"""[pépite 267] field-level source authority : chaque champ vient de sa source autoritaire, jamais de fallback."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.data_contract.field_level_source_authority import valider_enregistrement   # noqa: E402

AUTORITES = {"exchange_ts": "VENUE", "receive_ts": "COLLECTOR"}


def test_sources_correctes():
    r = valider_enregistrement({"exchange_ts": "VENUE", "receive_ts": "COLLECTOR"}, AUTORITES)
    assert r["conforme"] is True


def test_source_non_autoritaire():
    # receive_ts fourni par la venue (fallback opaque interdit)
    r = valider_enregistrement({"exchange_ts": "VENUE", "receive_ts": "VENUE"}, AUTORITES)
    assert r["etat"] == "VIOLATION" and r["violations"][0]["raison"] == "SOURCE_NON_AUTORITAIRE"


def test_source_absente():
    r = valider_enregistrement({"exchange_ts": "VENUE"}, AUTORITES)
    assert any(v["raison"] == "SOURCE_ABSENTE" for v in r["violations"])

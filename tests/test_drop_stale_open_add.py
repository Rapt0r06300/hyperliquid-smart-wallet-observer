"""[COPY-VAULT lot2 #46] drop OPEN/ADD trop vieux : droppé (missed opportunity), CLOSE/REDUCE jamais droppé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.drop_stale_open_add import decision, TRAITER, DROP   # noqa: E402


def test_open_trop_vieux_droppe():
    r = decision("OPEN", 5000.0, ttl_ms=1000.0)
    assert r["decision"] == DROP and r["missed_opportunity"] is True


def test_open_frais_traite():
    assert decision("ADD", 200.0, ttl_ms=1000.0)["decision"] == TRAITER


def test_close_jamais_droppe():
    r = decision("CLOSE", 999999.0, ttl_ms=1000.0)
    assert r["decision"] == TRAITER and r["raison"] == "REDUCTION_JAMAIS_DROP"

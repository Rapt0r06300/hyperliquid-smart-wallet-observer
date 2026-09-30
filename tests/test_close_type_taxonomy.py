"""[ALL #90] close-type taxonomy : succès économique distingué de timeout/risk-stop/etc ; inconnu -> UNKNOWN."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core import close_type_taxonomy as CT   # noqa: E402


def test_types_distincts():
    assert CT.classifier("take_profit hit")["type"] == CT.ECONOMIC_SUCCESS
    assert CT.classifier("order TIMEOUT")["type"] == CT.TIMEOUT
    assert CT.classifier("STOP_LOSS triggered")["type"] == CT.RISK_STOP


def test_succes_economique_flag():
    assert CT.classifier("SUCCESS target")["succes_economique"] is True
    assert CT.classifier("EMERGENCY unwind")["succes_economique"] is False


def test_inconnu_jamais_succes():
    r = CT.classifier("banana")
    assert r["type"] == CT.UNKNOWN_CLOSE and r["succes_economique"] is False

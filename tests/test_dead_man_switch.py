"""[ARB lot2 #10] dead-man switch : heartbeat perdu -> toutes les intentions actives annulées."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.dead_man_switch import DeadManSwitch   # noqa: E402


def test_heartbeat_frais_pas_declenche():
    d = DeadManSwitch(timeout_ms=10_000.0)
    d.heartbeat(1000.0)
    assert d.etat(5000.0)["declenche"] is False
    assert d.intentions_actives_apres(["i1", "i2"], now_ms=5000.0) == ["i1", "i2"]


def test_heartbeat_perdu_cancel_all():
    d = DeadManSwitch(timeout_ms=10_000.0)
    d.heartbeat(1000.0)
    assert d.etat(20_000.0)["declenche"] is True
    assert d.intentions_actives_apres(["i1", "i2"], now_ms=20_000.0) == []


def test_aucun_heartbeat_declenche():
    assert DeadManSwitch().etat(1000.0)["declenche"] is True


def test_temps_invalide_declenche_fail_closed():
    etat = DeadManSwitch().etat("not-a-timestamp")
    assert etat == {"declenche": True, "raison": "TEMPS_INVALIDE"}

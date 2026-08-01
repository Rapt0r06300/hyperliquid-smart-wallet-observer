"""[pépite 248] economic priority allocator : emergency hedge > close > arb hedge > entry > research."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.economic_priority_allocator import rang, ordonnancer   # noqa: E402


def test_ordre_priorite():
    assert rang("EMERGENCY_HEDGE") < rang("CLOSE") < rang("ARB_HEDGE") < rang("PROFITABLE_ENTRY") < rang("RESEARCH")


def test_ordonnancement():
    intents = [{"type": "RESEARCH", "id": 1}, {"type": "EMERGENCY_HEDGE", "id": 2}, {"type": "CLOSE", "id": 3}]
    r = ordonnancer(intents)
    assert [i["id"] for i in r["ordonnees"]] == [2, 3, 1]


def test_type_inconnu_dernier():
    r = ordonnancer([{"type": "???", "id": 1}, {"type": "CLOSE", "id": 2}])
    assert r["ordonnees"][0]["id"] == 2

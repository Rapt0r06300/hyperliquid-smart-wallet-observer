"""[lot2 #97] fast-path coordination des jambes : canal direct entre jambes appariées, sinon bus générique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.leg_coordination_fastpath import FastPathJambes   # noqa: E402


def test_fastpath_entre_jambes_appariees():
    fp = FastPathJambes(latence_fastpath_ms=0.5, latence_bus_ms=5.0)
    fp.apparier("legA", "legB")
    r = fp.envoyer("legA", "legB")
    assert r["voie"] == "FAST_PATH" and r["latence_ms"] == 0.5


def test_bus_si_non_appariees():
    fp = FastPathJambes()
    r = fp.envoyer("legA", "legC")
    assert r["voie"] == "BUS_GENERIQUE" and r["raison"] == "JAMBES_NON_APPARIEES"


def test_appariement_symetrique():
    fp = FastPathJambes()
    fp.apparier("legA", "legB")
    assert fp.appariees("legB", "legA") is True

"""[ALL lot2 #25] une instance par venue : le registre renvoie toujours la même instance (pas de fragmentation)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.api_governance.per_venue_connection import RegistreConnexions   # noqa: E402


def test_instance_reutilisee():
    reg = RegistreConnexions()
    a = reg.obtenir("HL")
    b = reg.obtenir("hl")                                # même venue (casse indifférente)
    assert a is b and reg.creations == 1


def test_une_instance_par_venue():
    reg = RegistreConnexions()
    reg.obtenir("HL")
    reg.obtenir("BINANCE")
    assert reg.nombre_instances("HL") == 1 and reg.creations == 2


def test_fabrique_personnalisee():
    reg = RegistreConnexions(fabrique=lambda v: {"venue": v, "limiter": "shared"})
    assert reg.obtenir("HL")["limiter"] == "shared"

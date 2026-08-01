"""[ARB #30] leg idempotency : un retry réseau réutilise le même leg_id, jamais une nouvelle jambe."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.leg_idempotency import leg_id, RegistreJambes   # noqa: E402


def test_leg_id_deterministe():
    a = leg_id("ep-1", "HL", 0)
    b = leg_id("ep-1", "hl", 0)                                  # casse venue indifférente
    assert a == b and a.startswith("leg_")


def test_retry_ne_cree_pas_de_jambe():
    reg = RegistreJambes()
    j1 = reg.obtenir_ou_creer("ep-1", "HL", 0)
    j2 = reg.obtenir_ou_creer("ep-1", "HL", 0)                   # retry réseau
    assert j1["leg_id"] == j2["leg_id"]
    assert j1["nouveau"] is True and j2["nouveau"] is False
    assert j2["retries"] == 1
    assert reg.nombre_jambes() == 1                              # une seule jambe distincte


def test_jambes_distinctes_par_index_et_venue():
    reg = RegistreJambes()
    reg.obtenir_ou_creer("ep-1", "HL", 0)
    reg.obtenir_ou_creer("ep-1", "BINANCE", 1)
    assert reg.nombre_jambes() == 2

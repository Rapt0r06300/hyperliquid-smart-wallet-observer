"""[lot2 #82] aggregate market-ready gate : stratégie inactive tant que toutes les sources ne sont pas prêtes."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.aggregate_market_ready_gate import pret   # noqa: E402


def test_toutes_pretes():
    assert pret({"carnet": True, "flux": "READY", "marks": "OK"})["pret"] is True


def test_une_non_prete():
    r = pret({"carnet": True, "flux": False})
    assert r["pret"] is False and "flux" in r["sources_non_pretes"]


def test_aucune_source():
    assert pret({})["pret"] is False

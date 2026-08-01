"""[ARB #22] invalidation-on-market-change : décision sur snapshot périmé -> REVALIDER, jamais exécuter."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.snapshot_invalidation import valider_snapshot   # noqa: E402


def test_snapshot_inchange_procede():
    r = valider_snapshot("snap-42", "snap-42")
    assert r["valide"] is True and r["action"] == "PROCEDER"


def test_snapshot_remplace_revalide():
    r = valider_snapshot("snap-42", "snap-43")
    assert r["valide"] is False and r["action"] == "REVALIDER" and r["raison"] == "SNAPSHOT_REMPLACE"


def test_snapshot_inconnu_revalide():
    r = valider_snapshot(None, "snap-43")
    assert r["valide"] is False and r["action"] == "REVALIDER"

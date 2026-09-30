"""[pépite 295] burst sizing snapshot : les partial fills d'un même ordre utilisent un equity snapshot cohérent."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.burst_sizing_snapshot import SnapshotEquityRafale   # noqa: E402


def test_snapshot_reutilise_sur_la_rafale():
    s = SnapshotEquityRafale()
    r1 = s.ratio_sizing("ord1", notional_cible=500.0, equity_courante=1000.0)   # fige 1000
    r2 = s.ratio_sizing("ord1", notional_cible=500.0, equity_courante=1200.0)   # equity bougé -> ignoré
    assert r1["ratio"] == 0.5 and r2["ratio"] == 0.5 and r2["equity_snapshot"] == 1000.0


def test_nouvel_ordre_nouveau_snapshot():
    s = SnapshotEquityRafale()
    s.ratio_sizing("ord1", 500.0, 1000.0)
    r = s.ratio_sizing("ord2", 500.0, 2000.0)
    assert r["ratio"] == 0.25 and r["nouveau_snapshot"] is True


def test_equity_invalide_au_premier_fill():
    s = SnapshotEquityRafale()
    assert s.ratio_sizing("ordX", 500.0, 0.0)["ratio"] == "UNMEASURABLE"

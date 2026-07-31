"""ALPHA P50 — basis persistant vs dislocation transiente : autocorr, demi-vie, classification, gate."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import basis_vs_latency as B  # noqa: E402


def _persistent(n=400):
    # marche aleatoire (niveaux tres autocorrelees ~1) = basis persistant
    s = 12345
    x = 10.0
    out = []
    for _ in range(n):
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        x += ((s % 20) - 10) / 1000.0
        out.append(x)
    return out


def _transient(n=400):
    # bruit iid autour de 10 (autocorr ~0) = dislocation transiente
    s = 999
    out = []
    for _ in range(n):
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        out.append(10.0 + ((s % 200) - 100) / 50.0)
    return out


def test_persistent_basis_detecte():
    c = B.classer_dislocation(_persistent(), dt_s=1.0)
    assert c["persistent_basis"] is True and c["autocorr1"] > 0.5


def test_transient_detecte():
    c = B.classer_dislocation(_transient(), dt_s=1.0)
    assert c["transient"] is True


def test_gate_cross_venue_bloque_basis():
    persistent = {"persistent_basis": True}
    assert B.gate_cross_venue(persistent, edge_bps=50.0, cost_bps=9.0)["trade"] is False   # basis hors scope
    transient = {"persistent_basis": False}
    assert B.gate_cross_venue(transient, edge_bps=15.0, cost_bps=9.0)["trade"] is True
    assert B.gate_cross_venue(transient, edge_bps=5.0, cost_bps=9.0)["trade"] is False       # edge<cout


def test_demi_vie():
    assert B.demi_vie_pas(0.5) is not None and B.demi_vie_pas(1.5) is None

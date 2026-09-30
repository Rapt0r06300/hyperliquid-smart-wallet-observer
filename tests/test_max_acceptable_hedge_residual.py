"""[pépite 228] maximum acceptable hedge residual : refuser si résidu structurel > seuil, malgré le spread."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.max_acceptable_hedge_residual import accepter   # noqa: E402


def test_residu_acceptable():
    r = accepter(0.001, 1.0, residu_max_bps=20.0)         # 10 bps <= 20
    assert r["accepter"] is True


def test_residu_trop_grand():
    r = accepter(0.005, 1.0, residu_max_bps=20.0)         # 50 bps > 20
    assert r["accepter"] is False and r["raison"] == "RESIDU_STRUCTUREL_TROP_GRAND"


def test_non_mesurable():
    assert accepter(None, 1.0)["accepter"] is False

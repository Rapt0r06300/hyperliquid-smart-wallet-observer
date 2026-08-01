"""[CROSS-VENUE lot2 #72] warm-up volatilité séparé : buffer dédié, distinct du warm-up carnet."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.volatility_warmup import WarmupVolatilite   # noqa: E402


def test_pret_au_minimum():
    w = WarmupVolatilite(min_observations=3)
    w.observer(n=2)
    assert w.pret()["pret"] is False
    w.observer(n=1)
    r = w.pret()
    assert r["pret"] is True and r["composante"] == "VOLATILITE"


def test_incomplet():
    w = WarmupVolatilite(min_observations=100)
    assert w.pret()["raison"] == "WARMUP_VOL_INCOMPLET"


def test_compte():
    w = WarmupVolatilite(min_observations=5)
    w.observer(n=3)
    assert w.pret()["n"] == 3

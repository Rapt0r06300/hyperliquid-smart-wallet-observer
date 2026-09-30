"""[CROSS-VENUE lot2 #73] warm-up trading-intensity séparé : buffer dédié (Avellaneda Hummingbot)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.trading_intensity_warmup import WarmupIntensite   # noqa: E402


def test_pret_au_minimum():
    w = WarmupIntensite(min_echantillons=2)
    w.observer(n=1)
    assert w.pret()["pret"] is False
    w.observer(n=1)
    r = w.pret()
    assert r["pret"] is True and r["composante"] == "TRADING_INTENSITY"


def test_incomplet():
    w = WarmupIntensite(min_echantillons=200)
    assert w.pret()["raison"] == "WARMUP_INTENSITE_INCOMPLET"


def test_independant_de_la_vol():
    w = WarmupIntensite(min_echantillons=1)
    w.observer(n=1)
    assert w.pret()["pret"] is True

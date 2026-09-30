"""[COPY-VAULT lot2 #62] cross-coin atomicity : equity et portefeuille complet d'un même cycle de lecture."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.cross_coin_atomicity import coherent   # noqa: E402


def test_meme_cycle_coherent():
    r = coherent(cycle_equity=42, cycles_positions={"BTC": 42, "ETH": 42})
    assert r["coherent"] is True and r["read_cycle_id"] == 42


def test_cycle_divergent():
    r = coherent(cycle_equity=42, cycles_positions={"BTC": 42, "ETH": 41})
    assert r["coherent"] is False and "ETH" in r["coins_divergents"]


def test_cycle_equity_manquant():
    assert coherent(cycle_equity=None, cycles_positions={"BTC": 42})["coherent"] is False

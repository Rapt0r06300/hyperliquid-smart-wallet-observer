"""[ARB #6] conversion stablecoin réelle : jamais 1:1, prix exécutable réel."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import stablecoin_conversion as SC   # noqa: E402


def test_conversion_utilise_le_prix_executable():
    assert SC.est_stable("USDT") is True and SC.est_stable("BTC") is False
    assert SC.convertir_stable_usd(1000.0, "USDT", prix_executable_usd=0.9985) == 998.5   # pas 1000
    assert SC.ecart_au_peg_bps(0.9985) == -15.0                                           # 15 bps sous le peg


def test_prix_absent_est_unmeasurable():
    assert SC.convertir_stable_usd(1000.0, "USDC", prix_executable_usd=None) == "UNMEASURABLE"
    assert SC.ecart_au_peg_bps(0.0) == "UNMEASURABLE"                                     # jamais supposer le peg

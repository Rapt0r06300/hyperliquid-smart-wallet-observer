"""[ARB #8] asset-equivalence registry : mapping explicite, jamais un rapprochement par nom."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.asset_equivalence_registry import RegistreEquivalence   # noqa: E402


def test_equivalences_declarees():
    reg = RegistreEquivalence()
    assert reg.canonique("WBTC") == "BTC" and reg.canonique("weth") == "ETH"
    assert reg.equivalents("BTC", "WBTC") is True
    assert reg.equivalents("BTC", "ETH") is False


def test_non_declare_nest_equivalent_a_rien():
    reg = RegistreEquivalence()
    assert reg.canonique("PEPE") is None
    assert reg.equivalents("PEPE", "PEPE") is False        # non déclaré -> jamais rapproché (même à lui-même)
    reg.declarer("PEPE", ["PEPE", "WPEPE"])
    assert reg.equivalents("PEPE", "WPEPE") is True        # une fois DÉCLARÉ, ok

"""[pépite 244] cross-module self-trade prevention : intentions opposées simultanées même venue/coin détectées."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.cross_module_self_trade_prevention import detecter   # noqa: E402


def test_self_trade_detecte():
    r = detecter([{"module": "arb", "venue": "HL", "coin": "BTC", "montant_signe": 80.0},
                  {"module": "copy", "venue": "HL", "coin": "BTC", "montant_signe": -50.0}])
    assert r["self_trade"] is True and r["conflits"][0]["delta_net"] == 30.0


def test_pas_de_conflit_meme_sens():
    r = detecter([{"module": "arb", "venue": "HL", "coin": "BTC", "montant_signe": 80.0},
                  {"module": "copy", "venue": "HL", "coin": "BTC", "montant_signe": 50.0}])
    assert r["self_trade"] is False


def test_venues_differentes():
    r = detecter([{"module": "a", "venue": "HL", "coin": "BTC", "montant_signe": 80.0},
                  {"module": "b", "venue": "BIN", "coin": "BTC", "montant_signe": -50.0}])
    assert r["self_trade"] is False

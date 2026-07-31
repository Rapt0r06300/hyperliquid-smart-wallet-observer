"""[ARB #9] contract-equivalence guard : même sous-jacent/type/multiplicateur/expiry/quote avant de comparer."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.contract_equivalence_guard import contrats_equivalents   # noqa: E402


def test_contrats_equivalents_via_registre():
    a = {"underlying": "BTC", "type": "perp", "multiplier": 1.0, "expiry": None, "quote": "USD"}
    b = {"underlying": "WBTC", "type": "perp", "multiplier": 1.0, "expiry": None, "quote": "USD"}
    assert contrats_equivalents(a, b)["equivalents"] is True and \
        contrats_equivalents(a, b)["underlying_canonique"] == "BTC"


def test_divergences_refusees():
    a = {"underlying": "BTC", "type": "perp", "multiplier": 1.0, "expiry": None, "quote": "USD"}
    mult = {**a, "multiplier": 10.0}
    exp = {**a, "expiry": "2026-12-25"}
    quote = {**a, "quote": "USDT"}
    sousj = {**a, "underlying": "ETH"}
    assert contrats_equivalents(a, mult)["divergences"] == ["multiplier"]
    assert contrats_equivalents(a, exp)["divergences"] == ["expiry"]
    assert contrats_equivalents(a, quote)["divergences"] == ["quote"]
    assert "underlying" in contrats_equivalents(a, sousj)["divergences"]

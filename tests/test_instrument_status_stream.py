"""[ALL lot2 #16] instrument-status stream : trade autorisé uniquement si TRADING (inconnu/halted -> refus)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.instrument_status_stream import CacheStatutInstrument, TRADING, HALTED   # noqa: E402


def test_trading_autorise():
    c = CacheStatutInstrument()
    c.mettre_a_jour("BTC", TRADING)
    assert c.peut_trader("BTC")["peut_trader"] is True


def test_halted_refuse():
    c = CacheStatutInstrument()
    c.mettre_a_jour("BTC", HALTED)
    r = c.peut_trader("BTC")
    assert r["peut_trader"] is False and r["raison"] == "INSTRUMENT_NON_TRADING"


def test_statut_inconnu_failclosed():
    assert CacheStatutInstrument().peut_trader("BTC")["peut_trader"] is False   # jamais tradé sans statut connu

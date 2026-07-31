"""[CROSS-VENUE #3] quotes simultanées : jamais un prix périmé comparé à un prix frais."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.cross_venue_quotes_simultaneous import quotes_simultanees   # noqa: E402


def test_deux_jambes_fraiches_sont_simultanees():
    q = {"HL": {"ts_ms": 1000, "bid": 100, "ask": 100.1}, "BINANCE": {"ts_ms": 1030, "bid": 100, "ask": 100.1}}
    r = quotes_simultanees(q, now_ms=1050, max_age_ms=100)
    assert r["simultanees"] is True and not r["stale"]


def test_une_jambe_perimee_invalide():
    q = {"HL": {"ts_ms": 1000}, "BINANCE": {"ts_ms": 500}}      # BINANCE périmée (550 ms) vs now
    r = quotes_simultanees(q, now_ms=1050, max_age_ms=100)
    assert r["simultanees"] is False and "BINANCE" in r["stale"]


def test_ts_absent_est_stale():
    r = quotes_simultanees({"HL": {"bid": 100}, "BINANCE": {"ts_ms": 1040}}, now_ms=1050, max_age_ms=100)
    assert r["simultanees"] is False and r["stale"]["HL"] == "TS_ABSENT"

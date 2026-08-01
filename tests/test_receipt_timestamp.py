"""[DATA lot2 #67] receipt_timestamp : séparé du timestamp exchange, latence = receipt - exchange."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.receipt_timestamp import annoter   # noqa: E402


def test_latence_calculee():
    r = annoter({"x": 1}, receipt_ts_ms=1050.0, exchange_ts_ms=1000.0)
    assert r["ok"] is True and r["latence_ms"] == 50.0


def test_exchange_ts_absent_non_mesurable():
    r = annoter({"x": 1}, receipt_ts_ms=1050.0)
    assert r["latence_ms"] == "UNMEASURABLE" and r["exchange_ts_ms"] is None


def test_receipt_manquant_rejete():
    assert annoter({"x": 1}, receipt_ts_ms=None)["ok"] is False

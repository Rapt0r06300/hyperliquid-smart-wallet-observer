"""[ARB #28] opportunity fingerprint : même dislocation dans la même fenêtre -> même empreinte (un épisode)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.opportunity_fingerprint import fingerprint   # noqa: E402


def test_meme_bucket_meme_empreinte():
    a = fingerprint(coin="BTC", venues=["HL", "BINANCE"], direction="LONG_HL", price_state="65000/65010",
                    ts_ms=1000.0, bucket_ms=1000.0)
    b = fingerprint(coin="BTC", venues=["BINANCE", "HL"], direction="long_hl", price_state="65000/65010",
                    ts_ms=1999.0, bucket_ms=1000.0)             # venues désordonnées, même bucket
    assert a == b


def test_bucket_different_empreinte_differente():
    a = fingerprint(coin="BTC", venues=["HL", "BINANCE"], direction="LONG_HL", price_state="65000/65010",
                    ts_ms=1000.0, bucket_ms=1000.0)
    c = fingerprint(coin="BTC", venues=["HL", "BINANCE"], direction="LONG_HL", price_state="65000/65010",
                    ts_ms=2000.0, bucket_ms=1000.0)
    assert a != c


def test_coin_different_empreinte_differente():
    a = fingerprint(coin="BTC", venues=["HL"], direction="LONG", price_state="x", ts_ms=0.0)
    d = fingerprint(coin="ETH", venues=["HL"], direction="LONG", price_state="x", ts_ms=0.0)
    assert a != d and len(a) == 16

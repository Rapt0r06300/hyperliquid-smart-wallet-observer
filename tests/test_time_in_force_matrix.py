"""TIF matrix: Hyperliquid GTC/IOC/ALO, fail closed for unsupported values."""
import sys
from pathlib import Path
RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
from hl_observer.order_lifecycle import time_in_force_matrix as TIF  # noqa: E402


def test_hyperliquid_canonical_tifs_are_allowed():
    assert TIF.tif_autorise("HL", TIF.GTC)["autorise"] is True
    assert TIF.tif_autorise("HL", TIF.IOC)["autorise"] is True
    assert TIF.tif_autorise("HL", TIF.ALO)["autorise"] is True


def test_legacy_post_only_normalizes_to_alo():
    r = TIF.tif_autorise("HL", TIF.POST_ONLY)
    assert r["autorise"] is True
    assert r["tif_normalise"] == TIF.ALO


def test_hyperliquid_does_not_invent_fok_or_gtd_support():
    assert TIF.tif_autorise("HL", TIF.FOK)["autorise"] is False
    assert TIF.tif_autorise("HL", TIF.GTD)["autorise"] is False


def test_binance_matrix_remains_independent():
    assert TIF.tif_autorise("BINANCE", TIF.IOC)["autorise"] is True
    assert TIF.tif_autorise("BINANCE", TIF.GTD)["autorise"] is False


def test_unknown_venue_or_tif_fails_closed():
    assert TIF.tif_autorise("KRAKEN", TIF.GTC)["autorise"] is False
    assert TIF.tif_autorise("HL", "ZZZ")["autorise"] is False

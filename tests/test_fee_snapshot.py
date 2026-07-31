"""[CROSS-VENUE #11] fee snapshot par épisode : barème figé, une modif ultérieure ne change pas le PnL passé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.fee_snapshot import SnapshotFrais   # noqa: E402


def test_snapshot_est_immuable():
    bareme = {"HL": {"maker_bps": 1.0, "taker_bps": 3.5}, "BINANCE": {"maker_bps": 1.0, "taker_bps": 4.0}}
    snap = SnapshotFrais("ep1", bareme)
    assert snap.frais_bps("HL", maker=False) == 3.5 and snap.frais_bps("BINANCE", maker=True) == 1.0
    h0 = snap.hash
    # une modification ULTÉRIEURE de la source ne doit PAS changer le snapshot (PnL passé figé)
    bareme["HL"]["taker_bps"] = 99.0
    assert snap.frais_bps("HL") == 3.5 and snap.hash == h0
    # la copie renvoyée ne permet pas non plus de muter l'état interne
    snap.bareme()["HL"]["taker_bps"] = 88.0
    assert snap.frais_bps("HL") == 3.5


def test_venue_absente_du_snapshot():
    snap = SnapshotFrais("ep2", {"HL": {"maker_bps": 1.0, "taker_bps": 3.5}})
    assert snap.frais_bps("KRAKEN") is None

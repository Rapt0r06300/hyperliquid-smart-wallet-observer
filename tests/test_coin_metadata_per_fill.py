"""[COPY-VAULT lot2 #51] version metadata du coin par fill : tick/lot/min_notional/status figés au moment du fill."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.coin_metadata_per_fill import attacher   # noqa: E402


def test_metadata_complete():
    r = attacher({"id": "f1"}, tick_size=0.01, lot_size=0.001, min_notional=10.0, status="trading")
    assert r["ok"] is True and r["fige"] is True and r["metadata"]["status"] == "TRADING"


def test_metadata_incomplete_refuse():
    r = attacher({"id": "f1"}, tick_size=0.01, lot_size=None, min_notional=10.0, status="TRADING")
    assert r["ok"] is False and "lot_size" in r["manquants"]


def test_status_manquant():
    r = attacher({"id": "f1"}, tick_size=0.01, lot_size=0.001, min_notional=10.0, status="")
    assert r["ok"] is False and "status" in r["manquants"]

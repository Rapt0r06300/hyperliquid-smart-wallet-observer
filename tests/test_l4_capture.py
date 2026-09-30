"""CHANTIER #4 — capture L4 / order-intent : parse le cycle, écrit canonique, reconstruit via order_intent."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import l4_capture as L4   # noqa: E402


def test_chantier4_capture_reconstruit_le_cycle(tmp_path):
    events = [
        {"order_id": "o1", "ts_ms": 0, "type": "NEW", "coin": "BTC", "side": "BUY", "px": 100.0, "sz": 1, "mid": 100.0},
        {"order_id": "o1", "ts_ms": 50, "type": "MODIFY", "coin": "BTC", "side": "BUY", "px": 100.1, "sz": 1},
        {"order_id": "o1", "ts_ms": 90, "type": "PARTIAL", "coin": "BTC", "side": "BUY", "px": 100.1, "sz": 0.5},
        {"order_id": "o1", "ts_ms": 120, "type": "FILL", "coin": "BTC", "side": "BUY", "px": 100.1, "sz": 0.5},
        {"order_id": "o2", "ts_ms": 10, "type": "NEW", "coin": "ETH", "side": "SELL", "px": 50.0, "sz": 2},
        {"order_id": "o2", "ts_ms": 30, "type": "CANCEL", "coin": "ETH", "side": "SELL", "px": 50.0, "sz": 2},
        {"order_id": "oX", "ts_ms": 5, "type": "BOGUS", "coin": "BTC"},          # type inconnu -> quarantaine
    ]
    out = tmp_path / "l4.jsonl"
    r = L4.capturer(events, str(out))
    assert r["verdict"] == "MEASURABLE" and r["n_cycles"] == 2 and r["n_captures"] == 6
    assert r["quarantaine"] == 1                              # le type inconnu n'est jamais supposé
    assert r["agrege"]["fill_ratio"] == 0.5 and r["agrege"]["cancel_ratio"] == 0.5 and out.exists()


def test_chantier4_sans_flux_est_blocked_external():
    assert L4.capturer(None)["verdict"] == "BLOCKED_EXTERNAL"
    assert L4.event_canonique({"type": "NEW"}) is None        # order_id manquant -> jamais une intention fabriquée

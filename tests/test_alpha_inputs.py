"""ALPHA FACTORY — couche d'entrées : adaptateurs, détecteurs d'événements, featurizers d'état."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import alpha_inputs as I  # noqa: E402


def test_adapter_wallet_filtre_et_trie(tmp_path):
    p = tmp_path / "w.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"adresse": "0xAAA", "coin": "BTC", "side": "LONG", "ts_ms": 200},
        {"adresse": "0xAAA", "coin": "BTC", "side": "SHORT", "ts_ms": 100},
        {"adresse": "0xBBB", "coin": "ETH", "side": "LONG", "ts_ms": 150},
    ]), encoding="utf-8")
    r = I.adapter_wallet(str(p), adresse="0xaaa")
    assert len(r) == 2 and r[0]["ts_ms"] == 100          # filtré + trié


def test_adapter_l4_blocked():
    assert I.adapter_l4()["statut"] == I.BLOCKED


def test_adapter_l4_loads_only_provenance_bound_capture(tmp_path):
    p = tmp_path / "l4.jsonl"
    provenance = {
        "provider": "public-node",
        "capture_run_id": "run-real-1",
        "native_event_id": "native-1",
        "received_at_ms": 1001,
    }
    p.write_text(json.dumps({
        "order_id": "order-1", "ts_ms": 1000, "type": "NEW", "coin": "BTC",
        "side": "BUY", "px": 100.0, "sz": 1.0, "provenance": provenance,
        "paper_read_only": True, "real_execution": False,
    }) + "\n", encoding="utf-8")

    result = I.adapter_l4(str(p))

    assert result["statut"] == I.UNMEASURABLE
    assert result["real_l4_session"] is True
    assert result["provenance_by_provider_coin"] is True
    assert result["paired_public_fills"] is False
    assert result["events"][0]["native_event_id"] == "native-1"


def test_adapter_l4_quarantines_unproven_rows(tmp_path):
    p = tmp_path / "l4.jsonl"
    p.write_text(json.dumps({
        "order_id": "order-1", "ts_ms": 1000, "type": "NEW", "coin": "BTC",
        "side": "BUY", "px": 100.0, "sz": 1.0,
        "paper_read_only": True, "real_execution": False,
    }) + "\n", encoding="utf-8")

    result = I.adapter_l4(str(p))

    assert result["events"] == []
    assert result["quarantaine"] == 1
    assert result["statut"] == I.UNMEASURABLE


def test_event_binance_shock():
    bbo = [{"bin_mid": 100.0}, {"bin_mid": 100.0}, {"bin_mid": 100.2}]  # +20 bps au pas 2
    assert I.event_binance_shock(bbo, seuil_bps=10.0) == [2]


def test_event_queue_depletion():
    q = [{"bid_size": 100, "ask_size": 100}, {"bid_size": 40, "ask_size": 100}]  # bid -60%
    assert I.event_queue_depletion(q, drop_frac=0.5) == [1]


def test_event_spread_transition():
    q = [{"bid": 100.0, "ask": 100.01, "mid": 100.005}] * 20 + [{"bid": 100.0, "ask": 100.1, "mid": 100.05}]
    assert 20 in I.event_spread_transition(q, mult=2.0, fenetre=20)


def test_event_twap_slice_et_wallet_action_unmeasurable():
    mo = [{"stade": "FIRST_SLICE"}, {"stade": "CONTINUATION"}, {"stade": "FIRST_SLICE"}]
    assert I.event_twap_slice(mo) == [0, 2]
    acts = I.event_wallet_action([{"ts_ms": 1, "coin": "BTC", "side": "LONG"}])
    assert acts[0]["action"] == I.UNMEASURABLE and acts[0]["direction"] == "LONG"


def test_state_buckets():
    q = {"bid": 100.0, "ask": 100.02, "mid": 100.01, "bid_size": 30, "ask_size": 10,
         "bid_depth": 3000, "ask_depth": 1000, "coin": "BTC", "ts": 1784420429.0}
    s = I.state_buckets(q, vol_bps=3.0)
    assert s["coin"] == "BTC" and s["imbalance_bucket"] != I.UNMEASURABLE
    assert s["spread_bucket"].startswith("b") and s["hour_bucket"].startswith("h")
    assert s["crowding"] == I.UNMEASURABLE          # densité métaordres même-sens non branchée

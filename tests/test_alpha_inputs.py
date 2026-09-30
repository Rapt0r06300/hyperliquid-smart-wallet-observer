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

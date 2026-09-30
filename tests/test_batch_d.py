"""ALPHA batch D — interfaces data + recherche : hf_recorder, multi_venue, queue_model, trigger_map,
hidden_vs_twap, lineage."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import hf_recorder as HF  # noqa: E402
from hl_observer.research import hidden_vs_twap as HT  # noqa: E402
from hl_observer.research import lineage as LG  # noqa: E402
from hl_observer.research import multi_venue as MV  # noqa: E402
from hl_observer.research import queue_model as QM  # noqa: E402
from hl_observer.research import trigger_map as TM  # noqa: E402


def test_hf_recorder_ts_manquant_jamais_now():
    ev = HF.normaliser_event({"coin": "BTC", "seq": 1, "exchange_ts": 1000}, receive_wall_ts=1005)
    assert ev["signal_ts"] is None and "signal_ts" in ev["ts_manquants"]   # manquant -> None, jamais now
    assert ev["exchange_ts"] == 1000


def test_hf_qualite_detecte_anomalies():
    evs = [HF.normaliser_event({"seq": 1, "exchange_ts": 10}, receive_wall_ts=12),
           HF.normaliser_event({"seq": 3, "exchange_ts": 9}, receive_wall_ts=11),   # gap seq + out-of-order
           HF.normaliser_event({"seq": 3, "exchange_ts": 13}, receive_wall_ts=14)]  # doublon seq
    q = HF.qualite(evs)
    assert q["gaps_seq"] >= 1 and q["doublons_seq"] >= 1 and q["out_of_order"] >= 1 and q["quality_ok"] is False


def test_multi_venue_nbbo():
    bbos = [{"venue": "BIN", "bid": 100.0, "ask": 100.2}, {"venue": "OKX", "bid": 100.1, "ask": 100.3}]
    n = MV.nbbo(bbos)
    assert n["nbbo_bid"] == 100.1 and n["nbbo_ask"] == 100.2 and n["croise"] is False


def test_queue_model():
    assert QM.fill_risk_averse(10.0, 15.0)["fill"] is True
    assert QM.fill_risk_averse(10.0, 5.0)["fill"] is False
    p = QM.fill_probabiliste(10.0, 10.0)["p_fill"]
    assert 0.0 < p < 1.0


def test_trigger_map_densite():
    trigs = [{"triggerPx": 101.0, "size": 5}, {"triggerPx": 101.05, "size": 5}, {"triggerPx": 99.0, "size": 1}]
    d = TM.densite_triggers(trigs, mid=100.0, bucket_bps=10.0)
    assert d["zone_dense_bps"] is not None and d["taille_zone_dense"] >= 5


def test_hidden_vs_twap():
    assert HT.impact_permanent_bps(100.0, 100.1) == 10.0
    r = HT.interaction(twap_sens=1, hidden_sens=1, impact_bps=10.0, depth_response=0.2)
    assert r["crowding_meme_sens"] is True and isinstance(r["toxicite"], float)


def test_lineage_leakage():
    ok = LG.tracer_feature("ofi", source="l2", source_ts_ms=100, decision_ts_ms=100)
    fuite = LG.tracer_feature("future_mid", source="l2", source_ts_ms=200, decision_ts_ms=100)
    assert ok["causality"] == "CAUSAL" and fuite["causality"] == "LEAKAGE"
    assert LG.auditer([ok, fuite])["ok"] is False

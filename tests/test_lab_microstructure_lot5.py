"""LOT 5 — collecteur microstructure dense : parseurs + univers + écriture prouvés sans réseau (Flo 25/07)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("mic", _ROOT / "tools" / "collecter_lab_microstructure.py")
MIC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MIC)


def test_univers_adaptatif_classe_par_volume_oi_liq():
    ctxs = {"BTC": {"vol24h": 1e9, "oi": 1e8}, "SOL": {"vol24h": 1e8, "oi": 1e7},
            "MEME": {"vol24h": 1e6, "oi": 1e5}, "MORT": {"vol24h": 0, "oi": 1e7}}
    u = MIC.univers_adaptatif(ctxs, k=2, liq_counts={"SOL": 100})
    assert set(u) == {"BTC", "SOL"}, "les 2 majors liquides ; MEME (petit) et MORT (volume nul) écartés"
    # l'activité de liquidation compte : SOL (×101) dépasse BTC malgré un volume×OI plus faible
    assert u[0] == "SOL", "le boost liquidation remonte SOL en tête"


def test_parser_l2book_top20_avec_tailles():
    msg = {"channel": "l2Book", "data": {"coin": "ETH", "time": 111,
           "levels": [[{"px": "100", "sz": "3"}], [{"px": "100.1", "sz": "4"}]]}}
    r = MIC.parser_l2book(msg)
    assert r["coin"] == "ETH" and r["bids"] == [(100.0, 3.0)] and r["asks"] == [(100.1, 4.0)]


def test_parser_trades_cote_agresseur():
    msg = {"channel": "trades", "data": [{"coin": "SOL", "side": "B", "px": "10", "sz": "5", "time": 1},
                                         {"coin": "SOL", "side": "A", "px": "10", "sz": "2", "time": 2}]}
    r = MIC.parser_trades(msg)
    assert r[0]["side"] == 1 and r[1]["side"] == -1 and r[0]["sz"] == 5.0


def test_parser_bbo_avec_tailles_obligatoires():
    msg = {"channel": "bbo", "data": {"coin": "BTC", "time": 9,
           "bbo": [{"px": "100", "sz": "2"}, {"px": "100.2", "sz": "3"}]}}
    r = MIC.parser_bbo(msg)
    assert r["bid_sz"] == 2.0 and r["ask_sz"] == 3.0
    assert MIC.parser_bbo({"channel": "bbo", "data": {"coin": "X"}}) is None    # sans tailles -> None


def test_ecriture_dense_seq_gap_checksum(tmp_path):
    seqs: dict = {}
    MIC.ecrire_micro(tmp_path, "bbo", [{"flux": "bbo", "coin": "BTC", "ts_ex": 100, "bid": 1, "ask": 2}], seqs=seqs)
    MIC.ecrire_micro(tmp_path, "bbo", [{"flux": "bbo", "coin": "BTC", "ts_ex": 90, "bid": 1, "ask": 2}], seqs=seqs)  # ts recule
    p = tmp_path / "runtime" / "research_lab" / "data" / "micro_bbo.jsonl"
    lignes = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    assert lignes[0]["seq"] == 1 and lignes[1]["seq"] == 2           # séquence par coin
    assert lignes[1]["gap"] == "TS_RECUL"                            # gap détecté (ts exchange en recul)
    assert all(len(l["checksum"]) == 12 and "ts_mono_ns" in l and l["real_execution"] is False for l in lignes)
    # ISOLATION : rien dans runtime/data (main)
    assert not (tmp_path / "runtime" / "data").exists()

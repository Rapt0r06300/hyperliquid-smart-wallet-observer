"""FIX-44 — REPLAY = FORWARD : un seul pipeline canonique end-to-end, résultat indépendant du mode.

Prouve : (1) replay (batch) == forward (streaming) sur les MÊMES événements ; (2) prefix-stable (aucun
look-ahead) ; (3) un log rejoué AVEC artefacts (doublons / hors-ordre / carnet périmé) donne les MÊMES fills
économiques (les artefacts sont filtrés, jamais exploités) ; (4) 0 ordre réel (paper_only).
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import paper_pipeline_e2e as PP        # noqa: E402
from hl_observer.research import replay_consistency as RC   # noqa: E402


def _events_reels():
    # flux réel : événements de marché + signaux lead_lag (stratégie ACTIVE), edge 30 bps > coût 9 bps
    clean, seq = [], 0
    for k in range(20):
        seq += 1
        clean.append({"seq": seq, "ts_ms": 1000 * k, "coin": "BTC", "mid": 100.0 + 0.01 * k})
        if k % 2 == 0:
            seq += 1
            clean.append({"seq": seq, "ts_ms": 1000 * k + 1, "coin": "BTC", "mid": 100.0 + 0.01 * k,
                          "strategy": "lead_lag", "side": 1, "edge_bps": 30.0})
    return clean


def test_fix44_replay_egale_forward_meme_pipeline():
    clean = _events_reels()
    fwd = PP.executer_forward(clean)          # streaming
    rep = PP.executer_replay(clean)           # batch rejoué
    assert RC.deterministe(fwd.decisions, rep.decisions)          # même pipeline -> mêmes décisions
    assert fwd.scoreboard() == rep.scoreboard()                  # le scoreboard ne dépend pas du mode
    sb = fwd.scoreboard()
    assert sb["n_fills"] == 10 and sb["net_bps_total"] > 0 and sb["net_bps_moyen"] == 21.0


def test_fix44_prefix_stable_aucun_look_ahead():
    clean = _events_reels()
    fwd = PP.executer_forward(clean)
    pref = PP.executer_forward(clean[:7])     # ne traiter qu'un préfixe
    assert RC.prefix_stable(fwd.decisions, pref.decisions)       # les décisions passées ne changent pas


def test_fix44_replay_avec_artefacts_donne_les_memes_fills():
    clean = _events_reels()
    fwd = PP.executer_forward(clean)
    # log rejoué SALE : chaque signal dupliqué (même seq) + un événement à carnet périmé en fin de flux
    sale = []
    for e in clean:
        sale.append(e)
        if e.get("strategy"):
            sale.append(dict(e))                                 # DOUBLON (seq déjà vue)
    sale.append({"seq": 10_000, "ts_ms": 10_000_000, "coin": "BTC", "mid": 100.0, "book_ts_ms": 0,
                 "strategy": "lead_lag", "side": 1, "edge_bps": 30.0})   # carnet périmé -> STALE -> filtré
    rep = PP.executer_replay(sale)
    fills_clean = [d for d in fwd.decisions if d["decision"] == "FILL"]
    fills_sale = [d for d in rep.decisions if d["decision"] == "FILL"]
    assert [f["seq"] for f in fills_clean] == [f["seq"] for f in fills_sale]   # artefacts filtrés, économie identique
    assert fwd.scoreboard()["net_bps_total"] == rep.scoreboard()["net_bps_total"]


def test_fix44_gate_scope_et_edge_et_zero_ordre_reel():
    # famille hors scope actif -> NO_TRADE (SCOPE) ; edge sous le coût -> NO_TRADE (EDGE_TROP_FAIBLE)
    evs = [
        {"seq": 1, "ts_ms": 0, "coin": "BTC", "mid": 100.0, "strategy": "carry", "side": 1, "edge_bps": 50.0},
        {"seq": 2, "ts_ms": 1, "coin": "BTC", "mid": 100.0, "strategy": "lead_lag", "side": 1, "edge_bps": 5.0},
        {"seq": 3, "ts_ms": 2, "coin": "BTC", "mid": 100.0, "strategy": "lead_lag", "side": 1, "edge_bps": 40.0},
    ]
    p = PP.executer_forward(evs)
    raisons = {d["seq"]: (d["decision"], d.get("raison")) for d in p.decisions}
    assert raisons[1] == ("NO_TRADE", "SCOPE")            # carry hors scope actif
    assert raisons[2] == ("NO_TRADE", "EDGE_TROP_FAIBLE")  # 5-9 < 0
    assert raisons[3][0] == "FILL"
    fills = [d for d in p.decisions if d["decision"] == "FILL"]
    assert all(f["intent"]["paper_only"] and not f["intent"]["real_execution"] for f in fills)  # 0 ordre réel

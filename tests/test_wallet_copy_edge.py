"""ALPHA — edge copyable wallet : sens du markout, votes indépendants (grappes), UNMEASURABLE, verdicts."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import wallet_copy_edge as W  # noqa: E402

JOUR = 86_400_000


def _rec(adr, coin, side, day, mid0, mid1, i=0):
    return {"adresse": adr, "coin": coin, "side": side, "ts_ms": day * JOUR + i * 1000,
            "mid_at_fill": mid0, "mid_forward": mid1, "ecart_fill_s": 14.0, "ecart_forward_s": 11.0}


def test_markout_signe():
    assert W.markout_bps(_rec("0xa", "BTC", "LONG", 1, 100.0, 101.0)) > 0    # long + mid monte
    assert W.markout_bps(_rec("0xa", "BTC", "SHORT", 1, 100.0, 99.0)) > 0    # short + mid baisse
    assert W.markout_bps(_rec("0xa", "BTC", "LONG", 1, 100.0, 99.0)) < 0


def test_memecoin_un_jour_un_coin_est_MORE_DATA():
    # 28 fills PUMP le MÊME jour, gros gains : 1 seule grappe -> 1 vote indépendant -> MORE_DATA.
    recs = [_rec("0xw", "PUMP", "LONG", 5, 100.0, 106.7, i=i) for i in range(28)]
    r = W.evaluer_wallet(recs, adresse="0xw")
    assert r["verdict"] == "MORE_DATA"
    assert r["n_independent"] <= 2 and r["n_raw"] == 28          # 28 fills corrélés = ~1 vote


def test_champs_unmeasurable_presents():
    recs = [_rec("0xw", "PUMP", "LONG", 5, 100.0, 106.0, i=i) for i in range(10)]
    r = W.evaluer_wallet(recs, adresse="0xw")
    for k in ("action_OPEN_ADD_REDUCE_CLOSE_FLIP", "capacity_usd", "fill_ratio", "markouts_sous_seconde"):
        assert r[k] == W.UNMEASURABLE


def test_edge_diversifie_positif_survit_LCB():
    # 12 grappes (3 coins × 4 jours), toutes ~+30 bps gross -> net +21, LCB>0 -> pas KILL, pas MORE_DATA.
    recs = []
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append(_rec("0xg", coin, "LONG", 10 + d, 100.0, 100.3, i=d))
    r = W.evaluer_wallet(recs, adresse="0xg")
    assert r["n_independent"] >= 8 and r["lcb_net_bps"] is not None and r["lcb_net_bps"] > 0
    assert r["verdict"] in ("CANDIDAT", "FORWARD_REQUIS")       # LCB>0 ; CORE peut manquer régimes


def test_edge_negatif_est_KILL():
    recs = []
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append(_rec("0xn", coin, "LONG", 10 + d, 100.0, 100.02, i=d))   # +2 bps gross < 9 coût
    r = W.evaluer_wallet(recs, adresse="0xn")
    assert r["verdict"] == "KILL" and r["lcb_net_bps"] <= 0


def test_charger_forward_filtre_adresse(tmp_path):
    import json
    p = tmp_path / "f.jsonl"
    lignes = [
        {"adresse": "0xAAA111", "coin": "BTC", "side": "LONG", "ts_ms": JOUR, "mid_at_fill": 100.0, "mid_forward": 101.0},
        {"adresse": "0xBBB222", "coin": "ETH", "side": "SHORT", "ts_ms": JOUR, "mid_at_fill": 50.0, "mid_forward": 49.0},
    ]
    p.write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
    assert len(W.charger_forward(str(p), adresse="0xaaa111")) == 1
    assert len(W.charger_forward(str(p))) == 2


def test_classer_population_ordonne_candidats_avant_kills(tmp_path):
    import json
    recs = []
    # wallet gagnant diversifié
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append({"adresse": "0xWIN", "coin": coin, "side": "LONG", "ts_ms": (10 + d) * JOUR,
                         "mid_at_fill": 100.0, "mid_forward": 100.3})
    # wallet perdant diversifié
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append({"adresse": "0xLOSE", "coin": coin, "side": "LONG", "ts_ms": (10 + d) * JOUR,
                         "mid_at_fill": 100.0, "mid_forward": 99.9})
    p = tmp_path / "pop.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in recs), encoding="utf-8")
    classement = W.classer_population(str(p), min_fills=5)
    assert classement[0]["wallet"] == "0xWIN"
    assert classement[-1]["wallet"] == "0xLOSE"

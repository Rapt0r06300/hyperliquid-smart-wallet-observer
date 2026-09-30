"""ALPHA — OFI/microprice/déséquilibre sur carnet L2 : sens des features, markout causal anti-trou, discipline OOS."""

import math
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import ofi_microprice as X  # noqa: E402


def _snap(ts, bid, ask, bs=10.0, as_=10.0, bd=None, ad=None, micro=None):
    mid = (bid + ask) / 2.0
    return {"ts": ts, "bid": bid, "ask": ask, "mid": mid,
            "bid_size": bs, "ask_size": as_,
            "bid_depth": bd if bd is not None else bs * mid,
            "ask_depth": ad if ad is not None else as_ * mid,
            "micro": micro if micro is not None else mid}


def test_ofi_l1_signe_pression_acheteuse():
    # bid qui monte + ask retiré vers le haut → OFI > 0 (pression acheteuse).
    prev = _snap(0, 100.0, 101.0, bs=5.0, as_=5.0)
    cur = _snap(1, 100.5, 101.5, bs=7.0, as_=5.0)
    assert X.ofi_l1(prev, cur) > 0
    # bid qui baisse → OFI < 0 (pression vendeuse).
    cur2 = _snap(1, 99.5, 101.0, bs=7.0, as_=5.0)
    assert X.ofi_l1(prev, cur2) < 0


def test_ofi_nan_si_tailles_absentes():
    prev = {"ts": 0, "bid": 100.0, "ask": 101.0, "mid": 100.5, "bid_size": float("nan"), "ask_size": 5.0}
    cur = {"ts": 1, "bid": 100.5, "ask": 101.5, "mid": 101.0, "bid_size": 7.0, "ask_size": 5.0}
    assert math.isnan(X.ofi_l1(prev, cur))


def test_features_caus_micro_tilt_et_imbalance():
    serie = [_snap(0, 100.0, 101.0, bs=10, as_=10, micro=100.5),
             _snap(1, 100.0, 101.0, bs=30, as_=10, micro=100.7)]  # bid lourd → micro > mid
    feats = X.features_causaux(serie)
    f = feats[0]
    assert f["imb_l1"] > 0                         # bid_size > ask_size
    assert f["micro_tilt_bps"] > 0                 # micro au-dessus du mid
    assert abs(f["spread_bps"] - (1.0 / 100.5 * 1e4)) < 1e-6


def _serie_imbalance_predit(n=4000, pas_s=10.0, edge_bps=6.0):
    """Carnet où un déséquilibre positif du pas t est suivi d'une hausse du mid au pas t+1 (continuation)."""
    serie = []
    mid = 100.0
    ts = 0.0
    prev_dir = 0
    for i in range(n):
        # applique le mouvement PRÉDIT par le déséquilibre précédent
        mid *= (1 + prev_dir * edge_bps / 1e4)
        d = 1 if (i % 2 == 0) else -1                # déséquilibre alterné, connu à t
        bs, as_ = (30.0, 10.0) if d > 0 else (10.0, 30.0)
        half = 0.00005 * mid                          # spread ~1 bp, ne noie pas l'edge
        serie.append(_snap(ts, mid - half, mid + half, bs=bs, as_=as_))
        prev_dir = d
        ts += pas_s
    return serie


def test_markout_gross_positif_quand_signal_predit():
    serie = _serie_imbalance_predit()
    feats = X.features_causaux(serie)
    m = X.markout_signal(feats, feature_key="imb_l1", seuil=0.1, horizon_pas=1, fee_bps=0.0, inclure_spread=False)
    assert m["n"] > 100 and m["gross_bps"] > 0      # le déséquilibre prédit bien la hausse suivante


def test_markout_rejette_fenetre_qui_enjambe_un_trou():
    # deux snapshots normaux puis un trou géant : la fenêtre h=1 traversant le trou est refusée.
    serie = [_snap(0, 100.0, 101.0, bs=30, as_=10),
             _snap(10, 100.0, 101.0, bs=30, as_=10),
             _snap(1_000_000, 200.0, 201.0, bs=30, as_=10)]  # +100% après un trou de ~11 jours
    feats = X.features_causaux(serie, dt_max_feat=60.0)
    m = X.markout_signal(feats, feature_key="imb_l1", seuil=0.1, horizon_pas=1, fee_bps=0.0,
                         dt_max=60.0, inclure_spread=False)
    # aucun markout ne doit capturer le saut de 100 % à travers le trou
    assert all(abs(e["gross_bps"]) < 5000 for e in m["events"])


def test_cout_rend_net_negatif_KILL():
    serie = _serie_imbalance_predit(edge_bps=6.0)
    r = X.experience_feature(X.features_causaux(serie), feature_key="imb_l1", horizon_pas=1,
                             fee_bps=9.0, bucket_s=50.0)
    # 6 bps de gross prédictif < 9 bps de coût → doit être tué, pas maquillé en vert.
    assert r["verdict"] == "KILL"
    assert r["net_bps_oos"] is not None and r["net_bps_oos"] < 0


def test_edge_sans_cout_survit_OOS():
    serie = _serie_imbalance_predit(edge_bps=6.0)
    r = X.experience_feature(X.features_causaux(serie), feature_key="imb_l1", horizon_pas=1,
                             fee_bps=0.0, bucket_s=50.0, inclure_spread=False)
    # sans coût, un vrai signal prédictif doit survivre à l'OOS (contrôle : la discipline ne tue pas le vrai edge).
    assert r["verdict"] == "OOS_POSITIF_A_FORWARD"
    assert r["lcb_net_bps"] is not None and r["lcb_net_bps"] > 0


def test_bruit_pur_ne_fabrique_pas_de_vert():
    # mid en marche aléatoire déterministe indépendante du déséquilibre → pas d'edge net positif.
    serie = []
    mid = 100.0
    s = 12345
    for i in range(4000):
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        mid *= (1 + ((s % 21) - 10) / 1e4)           # ±10 bps aléatoire, sans lien au carnet
        bs, as_ = (30.0, 10.0) if (s % 2 == 0) else (10.0, 30.0)
        half = 0.005 * mid
        serie.append(_snap(i * 10.0, mid - half, mid + half, bs=bs, as_=as_))
    r = X.experience_feature(X.features_causaux(serie), feature_key="imb_l1", horizon_pas=1,
                             fee_bps=9.0, bucket_s=50.0)
    assert r["verdict"] in ("KILL", "MORE_DATA")     # jamais OOS_POSITIF sur du bruit


def test_charger_book_csv(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text(
        "coin,ts,bid,ask,mid,micro,bid_size,ask_size,bid_depth_usd,ask_depth_usd,imbalance\n"
        "BTC,1.0,100.0,101.0,100.5,100.6,30,10,3000,1000,0.5\n"
        "BTC,2.0,100.0,101.0,100.5,100.6,30,10,3000,1000,0.5\n"   # ts distinct
        "BTC,2.0,100.0,101.0,100.5,100.6,30,10,3000,1000,0.5\n"   # doublon ts → dédup
        "ETH,1.0,10.0,10.1,10.05,10.06,5,5,50,50,0.0\n",
        encoding="utf-8")
    d = X.charger_book_csv(str(p))
    assert set(d) == {"BTC", "ETH"}
    assert len(d["BTC"]) == 2                          # doublon de ts supprimé
    assert d["BTC"][0]["bid_size"] == 30.0

"""HISTORICAL_HOLDOUT_V1 — parseur gelé, PROUVÉ sur fixtures locales (rectif Flo 25/07).

Prouve, sans réseau ni compte AWS : (1) décompression lz4 ; (2) attribution vault (les fills d'un non-vault
sont écartés) ; (3) jointure temporelle L2 ; (4) reconstruction des métaordres + stades ; (5) OFI top-5 ;
(6) coût exécutable L2 ; (7) placebo (alpha vs marché) ; (8) rapport (IC clusterisé + couverture + verdict,
aucune promotion si IC bas ≤ 0).
"""
from __future__ import annotations

import json

from hl_observer.experimental import historical_holdout as H

V1, V2, AUTRE = "0xvault1", "0xvault2", "0xother"
T0 = 1_700_000_000_000
HOR = 300_000


def _book(mid, *, bsz=50.0, asz=50.0):
    bid, ask = round(mid - 0.05, 3), round(mid + 0.05, 3)
    return {"levels": [[{"px": str(bid), "sz": str(bsz)}, {"px": str(bid - 0.1), "sz": "50"}],
                       [{"px": str(ask), "sz": str(asz)}, {"px": str(ask + 0.1), "sz": "50"}]]}


def _snap(coin, t, mid, **kw):
    b = _book(mid, **kw)
    return {"coin": coin, "time": t, "levels": b["levels"]}


def _l2_pour(coin, t, mid_entree, mid_horizon):
    """PRÉ (t-1s, bid petit), ENTRÉE (t, bid gros → OFI mesurable), HORIZON (t+5min)."""
    return [_snap(coin, t - 1000, mid_entree, bsz=40.0),
            _snap(coin, t, mid_entree, bsz=60.0),
            _snap(coin, t + HOR, mid_horizon, bsz=55.0)]


def _metaordre(vault, t0, mid_horizon):
    """5 slices taker même sens (BUY) espacés 10 s → FIRST + CONTINUATION + LATE. Rend (records_fills, snaps_SOL)."""
    recs, sol = [], []
    for i in range(5):
        t = t0 + i * 10_000
        recs.append({"time": t, "fills": [{"user": vault, "coin": "SOL", "px": "100.0", "sz": "1",
                                            "side": "B", "time": t, "hash": "h%s%d" % (vault, i),
                                            "oid": i, "tid": i, "crossed": True}]})
        sol += _l2_pour("SOL", t, 100.0, mid_horizon)
    return recs, sol


def _jeu():
    r1, sol1 = _metaordre(V1, T0, 100.5)                 # SOL monte → BUY gross positif
    r2, sol2 = _metaordre(V2, T0 + 3_600_000, 99.5)      # SOL baisse → BUY gross négatif
    autre = [{"user": AUTRE, "coin": "SOL", "px": "100", "sz": "9", "side": "B",
              "time": T0, "hash": "hother", "crossed": True}]           # forme À PLAT + non-vault → écarté
    node = r1 + r2 + autre
    btc = []
    for s in sol1 + sol2:                                  # BTC plat aux mêmes temps (placebo ≈ 0)
        btc.append(_snap("BTC", s["time"], 50000.0))
    return node, sol1 + sol2 + btc


def test_decompression_lz4_roundtrip():
    import lz4.frame
    brut = "\n".join(json.dumps({"user": V1, "coin": "SOL", "px": "1", "sz": "1", "time": T0}) for _ in range(3))
    comp = lz4.frame.compress(brut.encode("utf-8"))
    assert H.decompresser_lz4(comp).decode("utf-8") == brut               # (1) décompression


def test_attribution_vault_ecarte_les_autres():
    node, _ = _jeu()
    par_vc = H.charger_fills(node, [V1, V2])
    vaults = {v for (v, _c) in par_vc}
    assert vaults == {V1, V2} and AUTRE not in vaults                     # (2) attribution stricte
    assert all(c == "SOL" for (_v, c) in par_vc)


def test_pipeline_complet_prouve_les_8_points():
    node, l2 = _jeu()
    r = H.executer(node, l2, [V1, V2], coin_placebo="BTC")

    cov = r["couverture"]
    assert cov["cibles_taker"] > 0 and cov["l2_synchronise"] > 0          # (3) jointure temporelle L2
    assert cov["ofi_mesurable"] > 0                                       # (5) OFI mesurable
    assert r["n_metaordres"] == 2                                         # (4) 2 métaordres reconstruits
    # (4bis) stades CONTINUATION ET LATE présents dans la population
    assert {"CONTINUATION", "LATE_STAGE"} & set(r["par_stade"].keys())
    # (6) coût exécutable issu du L2 historique
    sigs = H.signaux_holdout(H.charger_fills(node, [V1, V2]), H.charger_l2(l2))
    pop = H.population_gelee(sigs)
    assert pop and all(s["cout_source"] == "l2_historique" for s in pop)
    assert all(s["ofi_top5"] is not None for s in pop)                    # OFI par slice
    # (7) placebo (alpha vs marché) calculé
    assert r["placebo_alpha_marche_ic"]["n_obs"] >= 1
    # (8) rapport : IC clusterisé + verdict ; IC bas ≤ 0 (flux ± symétrique) → aucune promotion
    assert r["pnl_net_bps_ic"]["n_clusters"] == 2
    assert r["verdict"] == "PAS_DE_PROMOTION_IC_BAS_NON_POSITIF"
    assert set(r["capacite"]["par_palier"].keys()) == {"10", "25", "50", "100", "250", "500"}


def test_slice_sans_L2_est_exclu_pas_reconstruit():
    # métaordre sans AUCUN carnet L2 → l2_sync False → population vide (pas d'approximation)
    node, _ = _metaordre(V1, T0, 100.5)
    r = H.executer(node, [], [V1])                                        # aucun L2
    assert r["couverture"]["l2_synchronise"] == 0 and r["n_metaordres"] in (0, None)
    assert r["verdict"] == "PAS_DE_PROMOTION_IC_BAS_NON_POSITIF"

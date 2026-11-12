"""Chantier latence : l'avantage de copie est-il capté à faible délai et perdu à long délai ?"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_executable as cv  # noqa: E402
from hl_observer.backtesting import copy_vault_latency_study as L  # noqa: E402

T0 = 1_800_000_600_000           # dix minutes après l'heure pile (aucun funding traversé)


def _carnet(ts, bid, *, ligne, connexion="cx", epoque=0):
    ask = bid + 2.0
    row = {"coin": "ETH", "ts_ms": ts, "bid": bid, "ask": ask, "capacity_usd": 50_000.0,
           "bids5": [[bid, 50_000.0 / bid]], "asks5": [[ask, 50_000.0 / ask]], "source_line": ligne,
           "causal_observation": True, "connection_id": connexion, "l2_gap_epoch": epoque}
    return row


def _metaordre():
    entree = {"event_id": "e1", "ts_ms": T0 + 1_000, "coin": "ETH", "direction": 1, "action": "ADD",
              "dir": "Open Long", "vault": "0xA", "taille_usd": 100.0, "move_frac": 0.01, "source": "LIVE_WS",
              "is_snapshot": False, "observed_at_ms": T0 + 1_025, "received_at_ms": T0 + 1_025}
    return cv.cluster_metaorders([entree])[0]


def test_la_derive_captee_tot_est_perdue_tard():
    """Le prix monte fort dans les 20 s après le signal puis se stabilise : entrer tôt gagne, tard paye le coût."""
    signal = T0 + 1_025                                      # observation (reception locale)
    # un carnet toutes les secondes ; le prix grimpe de 100 à 130 entre +5 s et +20 s, puis plat
    carnets = []
    for dt in range(700):                                   # 0..700 s, un carnet/s
        ts = signal + dt * 1_000
        if dt <= 5:
            bid = 100.0
        elif dt <= 20:
            bid = 100.0 + (dt - 5) * 2.0                     # +2/s de 5 à 20 s → 100 → 130
        else:
            bid = 130.0
        carnets.append(_carnet(ts, bid, ligne=dt + 1))
    metaordres = _metaordre()
    res = L.etude_latence(metaordres, {"ETH": carnets}, delais_ms=(5_000, 60_000), horizon_ms=300_000)
    par = {d["copy_delay_ms"]: d for d in res["par_delai"]}
    # à 5 s de délai : on entre à ~100 avant la montée → net fortement positif
    assert par[5_000]["net_bps_par_decision"] is not None and par[5_000]["net_bps_par_decision"] > 0
    # à 60 s de délai : on entre à 130 après la montée → la dérive est partie, net ≤ 0
    assert par[60_000]["net_bps_par_decision"] is not None
    assert par[60_000]["net_bps_par_decision"] < par[5_000]["net_bps_par_decision"]
    assert res["net_devient_positif_a_faible_delai"] is True
    assert res["gain_bps_en_copiant_plus_vite"] > 0
    assert "LE DÉLAI EST LE VERROU" in res["lecture"]


def test_sans_signal_executable_le_verdict_le_dit():
    metaordres = _metaordre()
    # carnets sans identité de connexion → le moteur refuse tout → aucun signal exécutable
    carnets = [dict(_carnet(T0 + 1_025 + i * 1_000, 100.0, ligne=i + 1), connection_id=None) for i in range(400)]
    for c in carnets:
        c.pop("connection_id", None)
        c.pop("l2_gap_epoch", None)
    res = L.etude_latence(metaordres, {"ETH": carnets}, delais_ms=(5_000, 60_000))
    assert res["meilleur_net_bps_par_decision"] is None
    assert "pas assez de signaux exécutables" in res["lecture"]
    assert all(d["signaux_executes"] == 0 for d in res["par_delai"])
    assert all("L2_CONNECTION_IDENTITY_INCOMPLETE" in d["refus_par_motif"] for d in res["par_delai"])


def test_tous_les_delais_sont_mesures():
    metaordres = _metaordre()
    carnets = [_carnet(T0 + 1_025 + i * 1_000, 100.0 + i * 0.01, ligne=i + 1) for i in range(800)]
    res = L.etude_latence(metaordres, {"ETH": carnets})
    assert [d["copy_delay_ms"] for d in res["par_delai"]] == list(L.DELAIS_MS)

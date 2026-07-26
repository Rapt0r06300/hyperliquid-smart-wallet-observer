"""LOT13 Part1+2 — mesure corrigée prouvée sans réseau (Flo 26/07)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("nac", _ROOT / "tools" / "native_alpha_v1_corrige.py")
NAC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NAC)


def _prix(base=100.0, pas=0.0, spread=0.02, n=60, t0=1_000_000.0, dt=200.0):
    return {"tps": [t0 + i * dt for i in range(n)],
            "rows": [(t0 + i * dt, base + i * pas - spread / 2, base + i * pas + spread / 2) for i in range(n)]}


def test_decompo_reconcile_brut_spread_frais_slippage():
    # prix qui MONTE de 1 bps/pas ; un long doit avoir brut_mid > 0 et net = brut - spread - frais - slip
    prix = _prix(base=100.0, pas=0.01)
    r = NAC.markout_decompose({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix, horizons=(5,), fee_ar_bps=9.0)
    h = r["par_horizon"]["5"]
    assert h["statut"] == "OK"
    recon = h["brut_mid_bps"] - h["spread_bps"] - h["frais_bps"] - h["slippage_bps"]
    assert abs(recon - h["net_bps"]) < 1e-6, "net = brut_mid - spread - frais - slippage (réconcilie)"
    assert h["brut_mid_bps"] > 0, "le mid monte -> brut positif pour un long"


def test_horizon_sous_seconde_non_mesurable_sans_donnee():
    # données espacées de 5 s : un horizon 0,1 s n'a AUCUNE cotation dedans -> NON_MESURABLE (jamais faux)
    prix = _prix(n=5, dt=5000.0)
    r = NAC.markout_decompose({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix, horizons=(0.1, 5))
    assert r["par_horizon"]["0.1"]["statut"] == "NON_MESURABLE"
    assert r["par_horizon"]["5"]["statut"] == "OK", "5 s mesurable, 0,1 s non (honnête)"


def test_lags_reels_rendus():
    prix = _prix(n=30)
    r = NAC.markout_decompose({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix, horizons=(1,))
    h = r["par_horizon"]["1"]
    assert "entree_lag_ms" in h and "sortie_lag_ms" in h and h["entree_lag_ms"] >= 0


def test_dedup_signaux_avant_markout():
    sigs = [{"ts_ms": 0, "coin": "X", "sens": 1}, {"ts_ms": 5000, "coin": "X", "sens": 1},   # <30s -> retiré
            {"ts_ms": 40000, "coin": "X", "sens": 1}]
    assert len(NAC._dedup_sigs(sigs, fenetre_ms=30000)) == 2


def test_fraicheur_croit_avec_l_horizon():
    assert NAC._fraicheur(0.1) < NAC._fraicheur(5) <= NAC._fraicheur(60)
    assert NAC._fraicheur(0.1) >= 120.0        # plancher


def test_serie_bbo_dense_tolere_absence_de_n():
    recs = [{"coin": "BTC", "ts_wall_ms": 0, "bid": 100, "ask": 100.1, "bid_sz": 2, "ask_sz": 3},           # sans n
            {"coin": "BTC", "ts_wall_ms": 1, "bid": 100, "ask": 100.1, "bid_sz": 2, "ask_sz": 3, "bid_n": 4, "ask_n": 1}]
    s = NAC.serie_bbo_dense(recs)
    assert s["BTC"][0][5] == 0 and s["BTC"][1][5] == 4

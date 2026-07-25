"""RAPID_ALPHA_SHADOW — RUN sur données réelles : exécution HL réelle (ask/bid), épisodes, gate 2 fenêtres.

Prouve sur fixtures : exécution LONG au ask (entrée)/bid (sortie) → net < gross (spread payé), NON_MESURABLE
sans cotation, dédup en épisodes (1 obs = 1 épisode), refus PROBE si trop peu d'épisodes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("rapid_alpha_run", _ROOT / "tools" / "rapid_alpha_run.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

T0 = 1_700_000_000_000


def _hl_montant(t_choc, hausse_bps=100.0):
    """HL [(recu_ms,bid,ask,mid)] qui monte de hausse_bps sur 5 s après le choc, spread 2 bps."""
    out = []
    for i in range(61):
        t = t_choc + i * 100
        mid = 100.0 * (1 + (hausse_bps / 1e4) * min((i * 100) / 5000.0, 1.0))
        out.append((t, round(mid - 0.01, 4), round(mid + 0.01, 4), round(mid, 4)))
    return out


def test_execution_reelle_ask_bid_et_non_mesurable():
    choc = {"t": T0, "dir": 1, "famille": "PRICE_SHOCK", "coin": "BTC"}
    m = M.mesurer_reel(choc, _hl_montant(T0), fee_ar_bps=9.0)
    assert m["statut"] == "OK"
    h = m["par_horizon"]["1000"]
    # LONG : entrée au ask, sortie au bid → net STRICTEMENT < gross (le spread est payé), et frais retirés
    assert h["net_bps"] < h["gross_bps"] and h["frais_ar"] == 9.0
    assert M.mesurer_reel(choc, [])["statut"] == "NON_MESURABLE"        # aucune cotation → jamais inventé


def test_episodes_dedup():
    base = {"statut": "OK", "coin": "BTC", "par_horizon": {"1000": {"statut": "OK", "net_bps": 1.0}}}
    m1 = dict(base, t=T0); m2 = dict(base, t=T0 + 500); m3 = dict(base, t=T0 + 100_000)   # m2 proche de m1
    eps = M.episodes([m1, m2, m3])
    assert len(eps) == 2                                                # m1+m2 = 1 épisode, m3 = 2e


def test_deux_fenetres_refus_si_peu():
    eps = [{"statut": "OK", "coin": "BTC", "t": T0 + i * 1000, "heure": 0,
            "par_horizon": {"1000": {"statut": "OK", "net_bps": 1.0}}} for i in range(10)]
    assert M.deux_fenetres_ep(eps, 1000, min_ep=20)["probe_armable"] is False

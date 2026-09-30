"""RAPID_ALPHA_SHADOW — lead-lag cross-venue, cœur PUR (rectif Flo 25/07).

Prouve : sérialisation des retours, détection d'un lead INJECTÉ (Binance devance HL de 2 pas → verdict CANDIDAT),
et KILL quand les deux séries sont INDÉPENDANTES. Aucun réseau. Aucune donnée réelle requise.
"""
from __future__ import annotations

import math
import random

from hl_observer.experimental import rapid_alpha_shadow as R

T0 = 1_700_000_000_000


def _mids_depuis_retours(rets, base=100.0):
    """[(ts_ms, mid)] à pas 1 s reconstruits depuis des retours bps."""
    mids, cum = [], 0.0
    for i, r in enumerate(rets):
        cum += r
        mids.append((T0 + i * 1000, base * math.exp(cum / 1e4)))
    return mids


def test_serie_retours_buckets_contigus():
    mids = _mids_depuis_retours([10.0, -5.0, 20.0])
    s = R.serie_retours(mids, 1000.0)
    assert len(s) == 2 and abs(s[0][1] - (-5.0)) < 0.5 and abs(s[1][1] - 20.0) < 0.5


def test_lead_binance_devance_hl_detecte_candidat():
    rnd = random.Random(0)
    bin_rets = [rnd.uniform(-40, 40) for _ in range(300)]
    hl_rets = [0.0, 0.0] + [r + rnd.uniform(-2, 2) for r in bin_rets[:-2]]   # HL suit Binance avec 2 pas de retard
    res = R.shadow_leadlag(_mids_depuis_retours(bin_rets), _mids_depuis_retours(hl_rets),
                           pas_ms=1000.0, lags_max=6, latence_ms=400.0)
    assert res["lead_lag_pas"] == 2                                          # Binance devance HL de 2 s
    assert res["corr"] is not None and res["corr"] > 0.8
    assert res["capturable_bps"] > res["cout_ar_bps"]                       # amplitude > coûts
    assert res["verdict"] == "CANDIDAT_LEAD_SCALE"


def test_series_independantes_kill():
    rnd = random.Random(1)
    bin_rets = [rnd.uniform(-40, 40) for _ in range(300)]
    hl_rets = [rnd.uniform(-40, 40) for _ in range(300)]                    # AUCUN lien
    res = R.shadow_leadlag(_mids_depuis_retours(bin_rets), _mids_depuis_retours(hl_rets),
                           pas_ms=1000.0, lags_max=6, latence_ms=400.0)
    assert res["verdict"] == "KILL_PAS_DE_LEAD_EXPLOITABLE"                 # corr trop faible → pas de lead


def test_correl_parfaite_et_nulle():
    assert abs(R.correl([1, 2, 3, 4, 5, 6, 7, 8], [1, 2, 3, 4, 5, 6, 7, 8]) - 1.0) < 1e-9
    assert R.correl([1, 1], [1, 1]) is None                                # < 8 points → None (pas d'invention)

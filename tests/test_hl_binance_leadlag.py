"""ALPHA — lead-lag HL↔Binance : détection du meneur + markout conditionnel + discipline OOS."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import hl_binance_leadlag as X  # noqa: E402


def _serie_binance_mene(n=2000, choc=20.0):
    """bin bouge par chocs périodiques ; hl COPIE le rendement Binance du pas précédent (Binance mène)."""
    serie = []
    hl = bn = 100.0
    ts = 0
    prev_bin_ret = 0.0
    for i in range(n):
        bin_ret = choc if (i % 10 == 0) else 0.0
        bn *= (1 + bin_ret / 1e4)
        hl *= (1 + prev_bin_ret / 1e4)
        serie.append((ts, hl, bn))
        ts += 100
        prev_bin_ret = bin_ret
    return serie


def test_detecte_binance_mene_a_lag_1():
    rends = X.rendements_bps(_serie_binance_mene())
    ll = X.lead_lag_crosscorr(rends, max_lag=5)
    assert ll["binance_mene"] is True and ll["peak_lag"] == 1


def test_markout_positif_quand_hl_suit_binance():
    rends = X.rendements_bps(_serie_binance_mene(choc=30.0))
    m = X.markout_conditionnel(rends, seuil_bps=10.0, horizon_pas=2, cout_bps=0.0)
    assert m["n"] > 0 and m["gross_bps"] > 0        # HL suit le choc Binance


def test_markout_net_deduit_le_cout():
    rends = X.rendements_bps(_serie_binance_mene(choc=30.0))
    brut = X.markout_conditionnel(rends, seuil_bps=10.0, horizon_pas=2, cout_bps=0.0)["gross_bps"]
    net = X.markout_conditionnel(rends, seuil_bps=10.0, horizon_pas=2, cout_bps=9.0)["net_bps"]
    assert abs(net - (brut - 9.0)) < 1e-6


def test_fenetres_non_chevauchantes_obs_independantes():
    rends = X.rendements_bps(_serie_binance_mene(n=1000, choc=30.0))
    m = X.markout_conditionnel(rends, seuil_bps=10.0, horizon_pas=5, cout_bps=0.0)
    # chocs tous les 10 pas, horizon 5 → au plus ~1 obs par choc, pas de double comptage
    assert m["n"] <= 100


def test_experience_rend_un_verdict_discipline():
    r = X.experience(_serie_binance_mene(n=3000, choc=25.0), cout_bps=9.0, horizon_pas=2)
    assert r["verdict"] in ("KILL", "MORE_DATA", "OOS_POSITIF_A_FORWARD")
    assert "net_bps_oos" in r and "lcb_net_bps" in r and r["real_execution"] is False


def test_serie_trop_courte_more_data():
    r = X.experience([(i, 100.0, 100.0) for i in range(50)])
    assert r["verdict"] == "MORE_DATA"

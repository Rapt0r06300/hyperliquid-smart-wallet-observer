"""CHANTIER #69 — maker queue/toxicity sur tape HF : fill queue-aware, sélection adverse, E[PnL|fill]."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import maker_tape_experience as MT   # noqa: E402


def _ep(mid_after, *, queue_ahead=10.0, vt=20.0, depl=0.5, edge=5.0, spread=2.0):
    return {"queue_ahead": queue_ahead, "volume_traversant": vt, "cancels_devant": 0.0, "side": "BUY",
            "mid_at_post": 100.0, "mid_after": mid_after, "queue_depletion": depl,
            "edge_brut_bps": edge, "spread_capture_bps": spread}


def test_chantier69_fill_toxique_est_kill():
    # rempli PUIS le marché tombe (mid 100 -> 99.9 = -10 bps) : sélection adverse -> toxicité haute -> E[PnL|fill]<0.
    toxiques = [_ep(99.9, depl=0.9, spread=2.0, edge=5.0) for _ in range(6)]
    r = MT.experience_maker_tape(toxiques, maker_fee_bps=1.0, tape_reelle=True)
    assert r["verdict"] == "KILL" and r["e_pnl_fill_median_bps"] < 0     # fill maker gratuit = toxique
    assert r["fill_rate"] == 1.0 and r["toxicity_mediane"] > 0.5


def test_chantier69_fill_propre_positif_mais_tape_synthetique_more_data():
    propres = [_ep(100.05, depl=0.2, spread=3.0, edge=5.0) for _ in range(6)]   # markout favorable, peu toxique
    syn = MT.experience_maker_tape(propres, maker_fee_bps=1.0, tape_reelle=False)
    reel = MT.experience_maker_tape(propres, maker_fee_bps=1.0, tape_reelle=True)
    assert syn["e_pnl_fill_median_bps"] > 0
    assert syn["verdict"] == "MORE_DATA" and syn["preuve_economique"] is False   # positif mais tape non réelle
    assert reel["verdict"] == "CANDIDAT" and reel["preuve_economique"] is True    # VRAIE tape HF -> preuve éco


def test_chantier69_non_fill_et_blocked():
    # queue devant > volume traversant -> pas de fill (jamais 'touché = rempli')
    non_fill = [{"queue_ahead": 100.0, "volume_traversant": 10.0, "side": "BUY",
                 "mid_at_post": 100.0, "mid_after": 100.0}]
    r = MT.experience_maker_tape(non_fill, tape_reelle=True)
    assert r["n_fills"] == 0 and r["verdict"] == "MORE_DATA"
    assert MT.experience_maker_tape(None)["verdict"] == "BLOCKED_EXTERNAL"        # sans tape HF réelle

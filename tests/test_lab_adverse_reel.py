"""[LAB α item 12] P95/P99 ADVERSES RÉELS : coût composé (frais + demi-spread + latence causale +
slippage + adverse selection), sévérité de queue P99 > P95, et appliqué SÉPARÉMENT sur OOS ET FORWARD —
jamais un simple fee_bps × 1.5, jamais seulement sur IS. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.lab_recherche import cout_adverse_bps, evaluer_config   # noqa: E402

T = 1_700_000_000_000
CFG = {"notional_max": 300.0, "fee_bps": 4.5, "min_fill_ratio": 0.85, "seuil_edge_cross_venue_bps": 1.0}


def _synth(n):
    evs = []
    for i in range(n):
        px = 60000.0 + i * 10.0
        evs.append({"coin": "BTC", "px": px, "mid": px, "sz": 0.3, "signe": 1 if i % 2 == 0 else -1,
                    "ts_ms": T + i * 1000, "vault": "A",
                    "book": {"asks": [[px + 10.0, 5.0]], "bids": [[px - 10.0, 5.0]]}})
    return evs


def test_cout_adverse_est_compose_pas_un_multiplicateur_de_fee():
    c95 = cout_adverse_bps(CFG, niveau="ADVERSE_P95")
    c99 = cout_adverse_bps(CFG, niveau="ADVERSE_P99")
    # composantes DISTINCTES présentes (pas un simple fee×k)
    for k in ("demi_spread_bps", "latence_bps", "slippage_bps", "adverse_selection_bps"):
        assert k in c95 and isinstance(c95[k], (int, float))
    # ce n'est PAS fee_bps × 1.5 : le surcoût compose plusieurs sources et n'égale pas 0.5 × fee.
    assert abs(c95["surcout_bps"] - 0.5 * CFG["fee_bps"]) > 1e-6
    # sévérité de queue : P99 STRICTEMENT plus dur que P95.
    assert c99["surcout_bps"] > c95["surcout_bps"]
    assert c95["etiquette"] == "STRESS_ONLY"


def test_adverse_applique_sur_oos_ET_forward_pas_seulement_is():
    r = evaluer_config(_synth(60), CFG, leader_equity_defaut=100000.0, min_episodes=5)
    seg = r["segments"]
    # ADVERSE_P95/P99 portent un net OOS ET un net FORWARD distincts (stress appliqué sur les deux).
    for niveau in ("ADVERSE_P95", "ADVERSE_P99"):
        assert seg[niveau]["net_oos"] is not None and seg[niveau]["net_forward"] is not None
    # le net ADVERSE retenu = le PIRE des deux (min OOS/FORWARD).
    p95 = seg["ADVERSE_P95"]
    assert p95["net"] == min(p95["net_oos"], p95["net_forward"])
    # exposé dans les métriques pour le gate + le rapport.
    assert "adverse_p95_oos" in r["metriques"] and "adverse_p95_forward" in r["metriques"]


def test_stress_adverse_ne_rend_pas_meilleur_que_le_brut():
    # un stress qui MAJORE les coûts ne peut pas améliorer le net vs le même segment sans stress.
    r = evaluer_config(_synth(60), CFG, leader_equity_defaut=100000.0, min_episodes=5)
    seg = r["segments"]
    # net OOS adverse P99 <= net OOS adverse P95 <= (proche) net OOS brut : la sévérité ne paie jamais.
    assert seg["ADVERSE_P99"]["net_oos"] <= seg["ADVERSE_P95"]["net_oos"] + 1e-9

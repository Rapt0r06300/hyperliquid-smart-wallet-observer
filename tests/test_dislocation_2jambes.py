"""CROSS_VENUE_DISLOCATION_FINAL — cœur 2 jambes prouvé sans données (Flo 25/07).

Prouve : (1) net 2 jambes/4 exécutions au bid/ask — une dislocation qui CONVERGE rapporte le basis moins
les coûts, un basis nul ne rapporte que les coûts (négatif) ; (2) backtester entre sur |basis|>seuil et
sort sur convergence, sans look-ahead ; (3) verdict ARME seulement si net+ 2 moitiés ET pf>1,2 ET LOO+.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bt", _ROOT / "tools" / "backtest_dislocation_2jambes.py")
BT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BT)


def test_net_positif_quand_le_basis_converge():
    # HL cher à l'entrée (100.2 vs 100.0), convergent à l'égalité à la sortie -> SHORT HL / LONG BIN gagne
    hl_in = (0, 100.19, 100.21); bn_in = (0, 99.99, 100.01)
    hl_out = (0, 100.00, 100.02); bn_out = (0, 99.99, 100.01)
    net = BT._net_trade_bps(hl_in, bn_in, hl_out, bn_out, sens=+1, fees_ar_bps=0.0)
    assert net > 0, "un basis qui converge (HL cher -> égal) rapporte, hors frais"
    # avec les frais réels (16 bps), un petit basis de ~20 bps ne couvre pas forcément : on vérifie le signe seul


def test_basis_nul_ne_rapporte_que_les_couts():
    q = (0, 100.0, 100.02)
    net = BT._net_trade_bps(q, (0, 100.0, 100.02), q, (0, 100.0, 100.02), sens=+1, fees_ar_bps=16.0)
    assert net < 0, "sans convergence, on ne paie que le spread croisé + frais -> négatif"


def test_backtester_entre_et_sort_sur_convergence_sans_lookahead():
    # série : basis ~40 bps puis converge à ~0. Doit produire 1 trade fermé en CONVERGENCE.
    evs = []
    t = 1_000_000.0
    # dislocation ouverte (HL cher de ~40 bps)
    for i in range(3):
        evs.append((t + i * 500, "HL", 100.20, 100.22))
        evs.append((t + i * 500, "BIN", 99.80, 99.82))
    # convergence (HL redescend au niveau BIN)
    for i in range(3, 6):
        evs.append((t + i * 500, "HL", 99.80, 99.82))
        evs.append((t + i * 500, "BIN", 99.80, 99.82))
    trades = BT.backtester({"ZZZ": evs}, seuil_entree=15.0, seuil_sortie=3.0, fees_ar_bps=0.0)
    assert len(trades) == 1 and trades[0]["sortie"] == "CONVERGENCE"
    assert trades[0]["ts_out"] > trades[0]["ts_in"], "sortie postérieure à l'entrée (causal)"
    assert trades[0]["net_bps"] > 0, "convergence de 40 bps hors frais = gain"


def test_quote_figee_bloque_la_decision():
    # BIN figée (une seule quote très vieille) -> fraîcheur dépassée -> aucun trade
    evs = [(0, "BIN", 99.8, 99.82)] + [(0 + 10000 + i * 500, "HL", 100.2, 100.22) for i in range(4)]
    trades = BT.backtester({"ZZZ": evs}, fraicheur_ms=3000.0)
    assert trades == [], "une jambe figée (>fraîcheur) ne doit jamais déclencher un trade"


def _trade(ts, net):
    return {"coin": "X", "ts_in": ts - 1, "ts_out": ts, "net_bps": net, "net_usd": net / 1e4 * 15}


def test_verdict_kill_si_une_moitie_negative():
    trades = [_trade(i, 5.0) for i in range(6)] + [_trade(6 + i, -5.0) for i in range(6)]
    assert BT.juger(trades)["verdict"] == "KILL"


def test_verdict_arme_si_robuste():
    trades = [_trade(i, 6.0) for i in range(12)]
    r = BT.juger(trades)
    assert r["verdict"] == "ARME_COHORTE" and r["pf"] == float("inf") and r["median_sans_meilleur_bps"] > 0


def test_verdict_kill_si_un_seul_trade_porte_le_gain():
    trades = [_trade(i, -1.0) for i in range(11)] + [_trade(11, 500.0)]
    assert BT.juger(trades)["verdict"] == "KILL", "leave-one-out : un seul gagnant ne suffit jamais"

"""BACKTEST DU FADE DE LIQUIDATIONS (expérience #2, 23/07). On prouve : la réversion est mesurée dans
le bon sens, les coûts sont déduits, BTC est exclu, et sous le seuil d'événements c'est NEED_MORE_DATA
— jamais un verdict sur du bruit."""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.fade_liquidation_backtest import (
    backtest, charger_evenements, reversion_bps, MIN_EVENEMENTS)


def _ev(coin, ov, m0, mf, ts=1000, h="30s"):
    return {"coin": coin, "overshoot_bps": ov, "mid_at_event": m0,
            "mid_fwd_%s" % h: mf, "ts_ms": ts}


def test_reversion_fade_dans_le_bon_sens():
    # SELL_OVERSHOOT (mid 100 sous oracle, ov<0) : le mid remonte à 100.3 -> fade LONG gagnant +30 bps
    assert round(reversion_bps(_ev("ETH", -50.0, 100.0, 100.3), horizon_s=30.0), 1) == 30.0
    # BUY_OVERSHOOT (ov>0) : le mid redescend -> fade SHORT gagnant
    assert round(reversion_bps(_ev("ETH", 50.0, 100.0, 99.7), horizon_s=30.0), 1) == 30.0
    # mid forward absent -> None (jamais comblé)
    assert reversion_bps({"coin": "ETH", "overshoot_bps": -50.0, "mid_at_event": 100.0},
                         horizon_s=30.0) is None


def test_sous_le_seuil_c_est_NEED_MORE_DATA(tmp_path):
    p = tmp_path / "runtime" / "data" / "overshoots_liquidation.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_ev("ETH", -50.0, 100.0, 100.3)) + "\n", encoding="utf-8")
    r = backtest(tmp_path)
    assert r["statut"] == "NEED_MORE_DATA" and r["evenements_utilisables"] == 1


def test_backtest_OOS_deduit_les_couts_et_exclut_BTC(tmp_path):
    p = tmp_path / "runtime" / "data" / "overshoots_liquidation.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    lignes = []
    # 60 événements ETH qui réversent de +40 bps (net +25 après 15 de coût) + du BTC qui doit être ignoré
    for i in range(60):
        lignes.append(json.dumps(_ev("ETH", -50.0, 100.0, 100.4, ts=1000 + i)))
    for i in range(10):
        lignes.append(json.dumps(_ev("BTC", -50.0, 100.0, 100.4, ts=1000 + i)))
    p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    r = backtest(tmp_path, min_evenements=MIN_EVENEMENTS)
    assert r["statut"] == "PROMETTEUR_OOS"
    assert "ETH" in r["out_of_sample"]["coins_net_positif"] and "BTC" not in r["out_of_sample"]["coins_net_positif"]
    assert abs(r["out_of_sample"]["net_moyen_bps"] - 25.0) < 0.5      # 40 réversion − 15 coût


def test_charger_survit_a_l_absence(tmp_path):
    assert charger_evenements(tmp_path) == []

"""LEAD-LAG SHADOW (chantier ARB, 23/07). On prouve la mécanique de mesure : un choc Binance, la
réaction HL à un horizon, l'entrée au demi-spread RÉEL, les coûts déduits -> PnL net ; et le garde
NEED_MORE_DATA tant qu'il n'y a pas assez de chocs. Aucun réseau : tape synthétique."""
from __future__ import annotations

import json

from hl_observer.backtesting.lead_lag_shadow import net_par_horizon, backtest


def test_net_par_horizon_mesure_la_reaction_apres_le_choc_moins_les_couts():
    # Binance saute +50 bps à t=10 ms ; HL réagit +40 bps à t=110 ms. Demi-spread HL 1 bps, frais 6.
    hl = [(5_000_000, 100.0, 99.99, 100.01), (110_000_000, 100.4, 100.39, 100.41)]
    bn = [(0, 100.0), (10_000_000, 100.5)]
    r = net_par_horizon(hl, bn, seuil_choc_bps=8.0, frais_slippage_bps=6.0, horizons_ms=[100.0])
    # net = réaction 40 − (2×demi_spread 1 + frais 6) = 40 − 8 = +32
    assert len(r[100.0]) == 1 and 30.0 < r[100.0][0] < 34.0


def test_un_choc_trop_petit_n_est_pas_un_evenement():
    hl = [(0, 100.0, 99.99, 100.01), (110_000_000, 100.02, 100.01, 100.03)]
    bn = [(0, 100.0), (10_000_000, 100.02)]                 # +2 bps < seuil 8 -> ignoré
    r = net_par_horizon(hl, bn, seuil_choc_bps=8.0, frais_slippage_bps=6.0, horizons_ms=[100.0])
    assert r[100.0] == []


def _tape(root, rows):
    p = root / "runtime" / "data" / "bbo_tape.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_backtest_NEED_MORE_DATA_sous_le_seuil_de_chocs(tmp_path):
    _tape(tmp_path, [{"venue": "BIN", "coin": "ETH", "recu_ns": 0, "mid": 100.0},
                     {"venue": "BIN", "coin": "ETH", "recu_ns": 10_000_000, "mid": 100.5},
                     {"venue": "HL", "coin": "ETH", "recu_ns": 5_000_000, "mid": 100.0, "bid": 99.99, "ask": 100.01},
                     {"venue": "HL", "coin": "ETH", "recu_ns": 110_000_000, "mid": 100.4, "bid": 100.39, "ask": 100.41}])
    assert backtest(tmp_path, horizons_ms=[100.0])["statut"] == "NEED_MORE_DATA"   # 1 choc < 30


def test_backtest_promet_quand_HL_suit_binance(tmp_path):
    rows = []
    for k in range(40):                                     # 40 chocs identiques -> assez pour juger
        base = k * 1_000_000_000
        rows += [{"venue": "BIN", "coin": "ETH", "recu_ns": base, "mid": 100.0},
                 {"venue": "BIN", "coin": "ETH", "recu_ns": base + 10_000_000, "mid": 100.5},
                 {"venue": "HL", "coin": "ETH", "recu_ns": base + 5_000_000, "mid": 100.0, "bid": 99.99, "ask": 100.01},
                 {"venue": "HL", "coin": "ETH", "recu_ns": base + 110_000_000, "mid": 100.4, "bid": 100.39, "ask": 100.41}]
    _tape(tmp_path, rows)
    r = backtest(tmp_path, horizons_ms=[100.0], min_chocs=30)
    assert r["statut"] == "PROMETTEUR" and r["net_par_horizon"][100.0]["net_moyen_bps"] > 0


def test_charger_survit_a_l_absence(tmp_path):
    assert backtest(tmp_path)["statut"] == "NEED_MORE_DATA"

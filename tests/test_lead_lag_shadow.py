"""LEAD-LAG SHADOW — méthodo gelée (chantier ARB, 23/07). On prouve : la distribution des intervalles
GÈLE les horizons observables, le CHOC vient des trades Binance, l'entrée paie le demi-spread HL réel,
et la stabilité se juge PAR PÉRIODE. Tape synthétique, aucun réseau."""
from __future__ import annotations

import json

from hl_observer.backtesting.lead_lag_shadow import (
    distribution_intervalles, horizons_observables, detecter_chocs, net_par_horizon,
    backtest, geler_config, CONFIG_GELE)


def test_distribution_intervalles_et_gating_des_horizons():
    ev = [(i * 200_000_000, 100.0, 99.9, 100.1) for i in range(20)]   # 1 message / 200 ms
    d = distribution_intervalles(ev)
    assert d["p50_ms"] == 200.0
    # HL n'émet que toutes les 200 ms -> un horizon < 400 ms n'est PAS observable
    assert horizons_observables(d, [50.0, 100.0, 250.0, 500.0, 1000.0]) == [500.0, 1000.0]


def test_detecter_chocs_sur_les_trades():
    trades = [(0, 100.0, 1.0), (10_000_000, 100.5, 1.0), (20_000_000, 100.51, 1.0)]
    chocs = detecter_chocs(trades, seuil_bps=8.0)                     # +50 bps puis +1 bps
    assert len(chocs) == 1 and chocs[0][1] == 1.0                     # un seul choc, direction +


def test_net_par_horizon_paie_le_demi_spread_reel_et_rend_la_capacite():
    hl = [(5_000_000, 100.0, 99.99, 100.01), (110_000_000, 100.4, 100.39, 100.41)]
    r = net_par_horizon(hl, [(10_000_000, 1.0)], frais_slippage_bps=6.0, horizons_ms=[100.0])
    net, cap = r[100.0][0]
    assert 30.0 < net < 34.0 and cap == 99.99                        # réaction 40 − (2×1 + 6) = 32


def _rows(n_chocs):
    # prix CONTINU (pas de reset entre blocs, sinon un faux choc baissier apparaît) : chaque bloc saute
    # de +50 bps sur Binance, HL suit de +40 bps 100 ms plus tard, et le bloc suivant repart d'en haut.
    rows = []
    px = 100.0
    for k in range(n_chocs):
        base = k * 1_000_000_000
        px_haut = px * 1.005                                          # +50 bps (choc Binance)
        px_hl = px * 1.004                                            # HL suit +40 bps
        rows += [{"venue": "BIN_TRADE", "coin": "ETH", "recu_ns": base, "px": px, "side": "BUY"},
                 {"venue": "BIN_TRADE", "coin": "ETH", "recu_ns": base + 10_000_000, "px": px_haut, "side": "BUY"}]
        for j in range(21):                                          # HL dense : 1 tick / 10 ms
            mid = px if j * 10 < 110 else px_hl
            rows.append({"venue": "HL", "coin": "ETH", "recu_ns": base + j * 10_000_000,
                         "mid": mid, "bid": mid * 0.9999, "ask": mid * 1.0001})
        px = px_haut                                                  # CONTINU : le bloc suivant repart d'ici
    return rows


def test_backtest_promet_quand_HL_suit_et_est_STABLE_par_periode(tmp_path):
    p = tmp_path / "runtime" / "data" / "bbo_tape.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in _rows(40)) + "\n", encoding="utf-8")
    r = backtest(tmp_path, horizons_ms=[100.0], min_chocs=30)
    assert r["statut"] == "PROMETTEUR"
    h = r["net_par_horizon"][100.0]
    assert h["esperance_nette_bps"] > 0 and h["stable"] and r["capacite_mediane_usd"] is not None


def test_backtest_NEED_MORE_DATA_si_tape_vide(tmp_path):
    assert backtest(tmp_path)["statut"] == "NEED_MORE_DATA"


def test_geler_config_ecrit_les_seuils_avant_le_live(tmp_path):
    cfg = geler_config(tmp_path, coins=["ETH", "SOL"], coins_controle=["DOGE"], horizons_ms=[100.0, 500.0])
    assert (tmp_path / CONFIG_GELE).exists()
    assert cfg["coins"] == ["ETH", "SOL"] and cfg["coins_controle"] == ["DOGE"]
    assert "critere_reussite" in cfg and cfg["horizons_ms"] == [100.0, 500.0]

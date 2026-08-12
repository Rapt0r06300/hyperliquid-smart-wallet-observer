"""[Stratégie Lead-Lag PAPER item 13] signal causal → entrée → sortie gelée → fill/missed → coûts →
ledger → PnL IS/OOS/FORWARD. Prouve l'ABSENCE de look-ahead (la décision ignore le move futur), les
coûts complets, le fill/missed, le placebo qui tue l'edge, et le découpage par épisodes. 0 réseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.strategies.lead_lag_paper import (   # noqa: E402
    SignalLeadLag, cout_components_bps, cout_total_bps, simuler_episode, rejouer_lead_lag)

CFG = {"notional": 100.0, "fee_bps": 2.5, "demi_spread_bps": 2.5,
       "slippage_bps": 1.0, "min_fill_ratio": 0.5, "costs_measured": True}


def test_signal_predictif_donne_un_fill_positif_apres_couts():
    sig = SignalLeadLag(ts_ms=1, coin="BTC", signe_leader=1, mid_entree=100.0, delta_mid_futur=0.5,
                        edge_bps_prevu=60.0, liquidite=1.0)
    r = simuler_episode(sig, config=CFG)
    assert r["statut"] == "FILLED"
    couts = cout_total_bps(CFG)
    # net = gross(50 bps) − coûts ; strictement positif mais STRICTEMENT inférieur au brut (coûts payés).
    assert 0 < r["pnl_usd"] < 50.0 / 1e4 * 100.0
    evts = [e["evt"] for e in r["ledger"]]
    assert evts == ["SIGNAL", "ENTREE", "SORTIE", "PNL"] and couts > 0
    assert r["opened_positions"] == r["closed_positions"] == 1
    assert r["LIQUIDATABLE_NET"] is True
    assert r["pnl_usd"] == round(
        r["gross_pnl_usd"] - r["fees_usd"] - r["spread_cost_usd"]
        - r["slippage_cost_usd"] - r["latency_cost_usd"], 8)


def test_decision_est_CAUSALE_pas_de_look_ahead():
    # edge PRÉVU sous les coûts -> NO_TRADE, MÊME si le move futur réalisé est énorme (aucun look-ahead).
    sig = SignalLeadLag(ts_ms=1, coin="BTC", signe_leader=1, mid_entree=100.0, delta_mid_futur=5.0,
                        edge_bps_prevu=3.0, liquidite=1.0)
    r = simuler_episode(sig, config=CFG)
    assert r["statut"] == "NO_TRADE" and r["pnl_usd"] == 0.0


def test_missed_fill_quand_liquidite_insuffisante():
    sig = SignalLeadLag(ts_ms=1, coin="BTC", signe_leader=1, mid_entree=100.0, delta_mid_futur=0.5,
                        edge_bps_prevu=60.0, liquidite=0.1)
    r = simuler_episode(sig, config=CFG)
    assert r["statut"] == "MISSED_FILL" and r["pnl_usd"] == 0.0


def test_sortie_gelee_signe_faux_perd():
    # leader dit +1 mais le move réalisé est négatif -> PnL négatif (la sortie gelée ne triche pas).
    sig = SignalLeadLag(ts_ms=1, coin="BTC", signe_leader=1, mid_entree=100.0, delta_mid_futur=-0.5,
                        edge_bps_prevu=60.0, liquidite=1.0)
    r = simuler_episode(sig, config=CFG)
    assert r["statut"] == "FILLED" and r["pnl_usd"] < 0


def _signaux(n, *, aligne=True):
    sigs = []
    for i in range(n):
        move = 0.5 if aligne else -0.5
        sigs.append(SignalLeadLag(ts_ms=1000 * i, coin="BTC" if i % 2 else "ETH", signe_leader=1,
                                  mid_entree=100.0, delta_mid_futur=move, edge_bps_prevu=60.0,
                                  liquidite=1.0))
    return sigs


def test_rejouer_is_oos_forward_et_placebo():
    r = rejouer_lead_lag(_signaux(30, aligne=True), config=CFG, min_episodes=5)
    seg = r["segments"]
    for lab in ("IS", "OOS", "FORWARD"):
        assert seg[lab]["net"] > 0 and seg[lab]["fills"] > 0        # edge réel positif partout
    # placebo (signe inversé) -> l'edge disparaît / s'inverse : net placebo négatif.
    assert r["placebo_net"] < 0
    # gate : tout positif + placebo rejeté + concentration OK (2 coins) -> PROMU.
    assert r["verdict"] == "PROMU"
    assert r["metriques"]["adverse_p95_net"] > 0 and r["real_execution"] is False


def test_edge_absent_ne_promeut_pas():
    # signaux non alignés (le leader se trompe) -> net négatif -> KILL, jamais un faux PROMU.
    r = rejouer_lead_lag(_signaux(30, aligne=False), config=CFG, min_episodes=5)
    assert r["segments"]["IS"]["net"] < 0 and r["verdict"] == "KILL"


def test_couts_non_prouves_restent_non_liquidables():
    cfg = {key: value for key, value in CFG.items() if key != "costs_measured"}
    result = simuler_episode(_signaux(1)[0], config=cfg)
    assert result["statut"] == "FILLED"
    assert result["LIQUIDATABLE_NET"] is False
    assert cout_components_bps(cfg)["costs_measured"] is False


def test_segment_deduplique_identite_stable():
    signals = _signaux(30)
    signals.insert(1, signals[0])
    result = rejouer_lead_lag(signals, config=CFG, min_episodes=5)
    duplicate_count = sum(seg["duplicate_trade_ids"] for seg in result["segments"].values())
    all_ids = [trade_id for seg in result["segments"].values() for trade_id in seg["trade_ids"]]
    assert duplicate_count == 1
    assert len(all_ids) == len(set(all_ids))

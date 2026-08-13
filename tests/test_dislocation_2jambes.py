"""CROSS_VENUE_DISLOCATION_FINAL — cœur 2 jambes prouvé sans données (Flo 25/07).

Prouve : (1) net 2 jambes/4 exécutions au bid/ask — une dislocation qui CONVERGE rapporte le basis moins
les coûts, un basis nul ne rapporte que les coûts (négatif) ; (2) backtester entre sur |basis|>seuil et
sort sur convergence, sans look-ahead ; (3) verdict ARME seulement si net+ 2 moitiés ET pf>1,2 ET LOO+.
"""
from __future__ import annotations

import importlib.util
import json
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
    assert trades[0]["ts_in"] >= trades[0]["ts_detect"] + BT.LATENCE_MS
    assert trades[0]["net_bps"] > 0, "convergence de 40 bps hors frais = gain"
    assert trades[0]["trade_id"]


def test_dislocation_disparue_pendant_latence_ne_trade_pas():
    t = 1_000_000.0
    evs = [
        (t, "HL", 100.20, 100.22),
        (t, "BIN", 99.80, 99.82),
        (t + 500, "HL", 99.80, 99.82),
        (t + 500, "BIN", 99.80, 99.82),
    ]
    assert BT.backtester({"ZZZ": evs}, latence_ms=400.0, fees_ar_bps=0.0) == []


def test_bbo_seul_ne_peut_pas_etre_liquidable_net():
    t = 1_000_000.0
    evs = []
    for i in range(3):
        evs.extend(((t + i * 500, "HL", 100.20, 100.22), (t + i * 500, "BIN", 99.80, 99.82)))
    for i in range(3, 6):
        evs.extend(((t + i * 500, "HL", 99.80, 99.82), (t + i * 500, "BIN", 99.80, 99.82)))
    summary = BT.juger(BT.backtester({"ZZZ": evs}, fees_ar_bps=0.0))
    assert summary["LIQUIDATABLE_NET"] is False
    assert summary["slippage_cost_usd"] is None


def test_profondeur_quatre_cotes_prouve_slippage_zero_et_reconciliation():
    t = 1_000_000.0
    evs = []
    for i in range(3):
        evs.extend(((t + i * 500, "HL", 100.20, 100.22), (t + i * 500, "BIN", 99.80, 99.82)))
    for i in range(3, 6):
        evs.extend(((t + i * 500, "HL", 99.80, 99.82), (t + i * 500, "BIN", 99.80, 99.82)))
    depth = {"ZZZ": [(t + i * 500, 250.0) for i in range(6)]}

    trades = BT.backtester(
        {"ZZZ": evs},
        fees_ar_bps=1.0,
        depth_by_coin=depth,
        notional_usd=15.0,
    )
    summary = BT.juger(trades)

    assert len(trades) == 1
    assert trades[0]["slippage_bps"] == 0.0
    assert trades[0]["entry_capacity_usd"] == 250.0
    assert trades[0]["exit_capacity_usd"] == 250.0
    assert trades[0]["LIQUIDATABLE_NET"] is True
    assert summary["slippage_cost_usd"] == 0.0
    assert summary["economic_reconciled"] is True
    assert summary["LIQUIDATABLE_NET"] is True


def test_profondeur_perimee_bloque_entree_plutot_que_inventer_fill():
    t = 1_000_000.0
    evs = []
    for i in range(3):
        evs.extend(((t + i * 500, "HL", 100.20, 100.22), (t + i * 500, "BIN", 99.80, 99.82)))
    depth = {"ZZZ": [(t - 10_000, 250.0)]}
    assert BT.backtester({"ZZZ": evs}, depth_by_coin=depth) == []


def test_basis_mid_ne_passe_pas_si_quatre_fills_sont_non_rentables():
    t = 1_000_000.0
    events = [
        # Les mids divergent, mais les spreads énormes absorbent toute convergence.
        (t, "ATOMIC", 99.90, 100.50, 99.50, 100.10),
        (t + 500, "ATOMIC", 99.90, 100.50, 99.50, 100.10),
        (t + 1000, "ATOMIC", 99.90, 100.50, 99.50, 100.10),
    ]
    depth = {"ZZZ": [(t + i * 500, 250.0) for i in range(3)]}
    diagnostics = {}

    trades = BT.backtester(
        {"ZZZ": events},
        depth_by_coin=depth,
        fees_ar_bps=1.0,
        diagnostics=diagnostics,
    )

    assert trades == []
    assert diagnostics["rejected_non_positive_executable_edge"] > 0


def test_trou_de_carnet_invalide_position_sans_faux_close_ni_pnl():
    t = 1_000_000.0
    events = [
        (t, "ATOMIC", 100.20, 100.22, 99.80, 99.82),
        (t + 500, "ATOMIC", 100.20, 100.22, 99.80, 99.82),
        # Le carnet revient une heure plus tard à convergence : ce n'est pas
        # une preuve du prix de sortie pendant le trou.
        (t + 3_600_000, "ATOMIC", 99.80, 99.82, 99.80, 99.82),
    ]
    depth = {
        "ZZZ": [
            (t, 250.0),
            (t + 500, 250.0),
            (t + 3_600_000, 250.0),
        ]
    }
    diagnostics = {}

    trades = BT.backtester(
        {"ZZZ": events},
        depth_by_coin=depth,
        fees_ar_bps=1.0,
        diagnostics=diagnostics,
    )

    assert trades == []
    assert diagnostics["positions_invalidated_gap"] == 1


def test_preuves_temporelles_ne_fabriquent_pas_forward_post_freeze():
    def complete_trade(index, net, *, timestamp):
        notional = 15.0
        fee = 0.01
        return {
            "trade_id": f"id-{index}",
            "coin": "X",
            "ts_detect": timestamp,
            "ts_in": timestamp + 1,
            "ts_out": timestamp + 2,
            "net_bps": net / notional * 1e4,
            "net_usd": net,
            "notional_usd": notional,
            "gross_reconciled_bps": (net + fee) / notional * 1e4,
            "fees_bps": fee / notional * 1e4,
            "spread_cost_bps": 0.0,
            "slippage_bps": 0.0,
            "latency_cost_bps": 0.0,
            "LIQUIDATABLE_NET": True,
            "two_leg": True,
        }

    trades = [complete_trade(i, 0.1, timestamp=1000 + i * 10) for i in range(10)]
    placebo = [complete_trade(f"p{i}", -0.1, timestamp=1000 + i * 10) for i in range(10)]
    evidence = BT.construire_preuves_temporelles(trades, placebo, frozen_at_ms=2000)

    assert evidence["oos"]["net_pnl_usd"] > 0
    assert evidence["placebos"]["beaten"] is True
    assert evidence["forward"]["sample_count"] == 0
    assert evidence["forward"]["post_freeze"] is False


def test_calibration_ne_transmet_que_le_train_a_la_selection(monkeypatch):
    series = {
        "ZZZ": [
            (float(index * 1000), "ATOMIC", 100.20, 100.22, 99.80, 99.82)
            for index in range(100)
        ]
    }
    depth = {"ZZZ": [(float(index * 1000), 250.0) for index in range(100)]}
    calls = []

    def fake_selector(train_series, train_depth):
        calls.append({
            "series_max": max(row[0] for rows in train_series.values() for row in rows),
            "depth_max": max(row[0] for rows in train_depth.values() for row in rows),
        })
        return {
            "status": "KILL_TRAIN",
            "selected": {
                "parameters": dict(BT.CROSS_WALK_FORWARD_GRID[0]),
                "summary": {},
                "eligible": False,
            },
            "candidate_count": 1,
            "eligible_candidate_count": 0,
            "candidates": [],
        }

    monkeypatch.setattr(BT, "selectionner_parametres_train", fake_selector)
    first = BT.calibrer_walk_forward(series, depth)
    # Une mutation exclusivement post-train ne peut pas changer ce que voit
    # la fonction de sélection.
    series["ZZZ"][-1] = (99_000.0, "ATOMIC", 500.0, 501.0, 1.0, 2.0)
    second = BT.calibrer_walk_forward(series, depth)

    assert first["bounds"] == second["bounds"]
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[0]["series_max"] <= first["bounds"]["train_end_ms"]
    assert calls[0]["depth_max"] <= first["bounds"]["train_end_ms"]


def test_walk_forward_purge_et_forward_apres_gel_uniquement(monkeypatch):
    parameters = dict(BT.CROSS_WALK_FORWARD_GRID[0])
    frozen = {
        **BT.walk_forward_protocol_signature(),
        "walk_forward_bounds": {
            "status": "READY",
            "first_observed_ms": 0.0,
            "train_end_ms": 10_000.0,
            "validation_start_ms": 20_000.0,
            "validation_end_ms": 30_000.0,
            "oos_start_ms": 40_000.0,
            "calibration_data_end_ms": 50_000.0,
        },
        "selected_strategy_parameters": parameters,
        "training_selection_eligible": False,
    }
    calls = []

    def fake_replay(series, depth, params, *, start_ms, end_ms, direction_multiplier=1):
        calls.append((start_ms, end_ms, direction_multiplier))
        return [], {}

    monkeypatch.setattr(BT, "_replay_segment", fake_replay)
    result = BT.evaluer_walk_forward_gelé(
        {}, {}, frozen_parameters=frozen, frozen_at_ms=60_000.0
    )

    assert calls[:4] == [
        (0.0, 10_000.0, 1),
        (20_000.0, 30_000.0, 1),
        (40_000.0, 50_000.0, 1),
        (60_001.0, None, 1),
    ]
    assert calls[4] == (40_000.0, 50_000.0, -1)
    assert result["status"] == "KILL_HISTORICAL"


def test_carnet_atomique_rejoue_les_deux_jambes_sans_etat_intermediaire(tmp_path: Path):
    source = tmp_path / "runtime" / "data" / "carnet_venues.jsonl"
    source.parent.mkdir(parents=True)
    rows = []
    for index in range(3):
        rows.append({
            "coin": "ZZZ", "collecte_ts": 1000.0 + index * 0.5,
            "hl_bid": 100.20, "hl_ask": 100.22,
            "bin_bid": 99.80, "bin_ask": 99.82, "taille_min_usd": 250.0,
        })
    for index in range(3, 6):
        rows.append({
            "coin": "ZZZ", "collecte_ts": 1000.0 + index * 0.5,
            "hl_bid": 99.80, "hl_ask": 99.82,
            "bin_bid": 99.80, "bin_ask": 99.82, "taille_min_usd": 250.0,
        })
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    series, depth, meta = BT.collecter_carnet_series(tmp_path)
    trades = BT.backtester(series, depth_by_coin=depth, fees_ar_bps=1.0)

    assert len(series["ZZZ"]) == 6
    assert all(event[1] == "ATOMIC" and len(event) == 6 for event in series["ZZZ"])
    assert meta["valid_snapshots"] == 6
    assert meta["source_mode"] == "ATOMIC_FOUR_SIDE_BOOK"
    assert len(trades) == 1
    assert trades[0]["LIQUIDATABLE_NET"] is True
    assert trades[0]["sortie"] == "CONVERGENCE"


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

"""LEAD-LAG SHADOW — méthodo gelée (chantier ARB, 23/07). On prouve : la distribution des intervalles
GÈLE les horizons observables, le CHOC vient des trades Binance, l'entrée paie le demi-spread HL réel,
et la stabilité se juge PAR PÉRIODE. Tape synthétique, aucun réseau."""
from __future__ import annotations

import gzip
import json

import pytest

from hl_observer.backtesting.lead_lag_evidence import (
    SCHEMA_VERSION,
    FrozenLeadLagEvidenceError,
    validate_frozen_evidence,
)
from hl_observer.backtesting.lead_lag_shadow import (
    CAMPAIGN_EXECUTION_MODEL,
    CAMPAIGN_HORIZON_MS,
    CONFIG_GELE,
    GLOBAL_TRIAL_LEDGER,
    backtest,
    calibrate_freeze_readiness,
    charger_tape,
    detecter_chocs,
    detecter_chocs_fenetre,
    distribution_intervalles,
    geler_config,
    horizons_observables,
    executable_campaign_evidence,
    episodes_par_horizon,
    net_par_horizon,
    selectionner_sources,
    summarize_executable_episodes,
    walk_forward_protocol_signature,
)
from hl_observer.experimental.signaux import signaux_lead_lag


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


def test_detecter_chocs_fenetre_capture_un_mouvement_cumulatif_causal():
    trades = [
        (0, 100.00, 1.0),
        (100_000_000, 100.03, 1.0),
        (200_000_000, 100.06, 1.0),
        (300_000_000, 100.09, 1.0),
        (400_000_000, 100.12, 1.0),
    ]

    assert detecter_chocs(trades, seuil_bps=8.0) == []
    shocks = detecter_chocs_fenetre(
        trades,
        seuil_bps=8.0,
        fenetre_ms=250.0,
    )

    assert shocks == [(300_000_000, 1.0)]


def test_detecter_chocs_fenetre_refuse_une_reference_trop_ancienne():
    trades = [
        (0, 100.0, 1.0),
        (5_000_000_000, 101.0, 1.0),
    ]

    assert detecter_chocs_fenetre(
        trades,
        seuil_bps=8.0,
        fenetre_ms=250.0,
    ) == []


def test_net_par_horizon_est_causal_et_mesure_la_capacite_top_of_book():
    hl = [
        (5_000_000, 100.0, 99.99, 100.01, 2.0, 2.0),
        (15_000_000, 100.0, 99.99, 100.01, 2.0, 2.0),
        (110_000_000, 100.4, 100.39, 100.41, 2.0, 2.0),
    ]
    r = net_par_horizon(hl, [(10_000_000, 1.0)], frais_slippage_bps=6.0, horizons_ms=[100.0])
    net, cap = r[100.0][0]
    assert 30.0 < net < 34.0
    assert cap == pytest.approx(200.02)


def test_episode_refuse_la_fausse_capacite_si_taille_bbo_absente():
    hl = [
        (15_000_000, 100.0, 99.99, 100.01),
        (110_000_000, 100.4, 100.39, 100.41),
    ]
    rows = episodes_par_horizon(
        hl,
        [(10_000_000, 1.0)],
        frais_slippage_bps=6.0,
        horizons_ms=[100.0],
        coin="ETH",
    )[100.0]
    assert len(rows) == 1
    assert rows[0]["entry_ts_ns"] >= rows[0]["signal_ts_ns"]
    assert rows[0]["top_capacity_usd"] is None
    assert rows[0]["liquidatable_net"] is False


def test_episode_ne_peut_pas_entrer_sur_la_cotation_pre_signal():
    hl = [
        (5_000_000, 100.0, 99.99, 100.01, 2.0, 2.0),
        (20_000_000, 101.0, 100.99, 101.01, 2.0, 2.0),
        (110_000_000, 101.4, 101.39, 101.41, 2.0, 2.0),
    ]
    row = episodes_par_horizon(
        hl,
        [(10_000_000, 1.0)],
        frais_slippage_bps=6.0,
        horizons_ms=[100.0],
    )[100.0][0]
    assert row["entry_ts_ns"] == 20_000_000
    assert row["entry_price"] == 101.01


def test_episode_reconcilie_tous_les_couts_en_dollars():
    hl = [
        (5_000_000, 100.0, 99.99, 100.01, 10.0, 10.0),
        (15_000_000, 100.1, 100.09, 100.11, 10.0, 10.0),
        (110_000_000, 100.5, 100.49, 100.51, 10.0, 10.0),
    ]
    row = episodes_par_horizon(
        hl,
        [(10_000_000, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=[100.0],
        coin="ETH",
        notional_usd=25.0,
    )[100.0][0]

    assert row["liquidatable_net"] is True
    assert row["entry_ts_ns"] >= row["signal_ts_ns"]
    assert row["latency_cost_usd"] > 0
    assert row["spread_cost_usd"] > 0
    assert row["fees_usd"] > 0
    assert row["gross_pnl_usd"] - row["fees_usd"] - row["spread_cost_usd"] \
        - row["slippage_cost_usd"] - row["latency_cost_usd"] \
        == pytest.approx(row["net_pnl_usd"])

    summary = summarize_executable_episodes([row])
    assert summary["positions_ouvertes"] == summary["positions_fermees"] == 1
    assert summary["economic_reconciliation_ok"] is True
    assert summary["LIQUIDATABLE_NET"] is True
    assert summary["trade_ids_count"] == 1


def test_episode_sans_quote_pre_signal_ne_certifie_pas_le_pnl():
    hl = [
        (15_000_000, 100.1, 100.09, 100.11, 10.0, 10.0),
        (110_000_000, 100.5, 100.49, 100.51, 10.0, 10.0),
    ]
    row = episodes_par_horizon(
        hl,
        [(10_000_000, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=[100.0],
    )[100.0][0]

    assert row["reference_status"] == "MISSING_PRE_SIGNAL_QUOTE"
    assert row["liquidatable_net"] is False
    summary = summarize_executable_episodes([row])
    assert summary["positions_fermees"] == 0
    assert summary["observations_non_liquidables"] == 1
    assert summary["LIQUIDATABLE_NET"] is False


def test_episode_refuse_une_reference_pre_signal_issue_d_un_ancien_shard():
    day_ns = 24 * 60 * 60 * 1_000_000_000
    signal_ns = 4 * day_ns
    hl = [
        (5_000_000, 90.0, 89.99, 90.01, 10.0, 10.0),
        (signal_ns + 20_000_000, 100.0, 99.99, 100.01, 10.0, 10.0),
        (signal_ns + 110_000_000, 100.5, 100.49, 100.51, 10.0, 10.0),
    ]
    row = episodes_par_horizon(
        hl,
        [(signal_ns, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=[100.0],
    )[100.0][0]

    assert row["reference_status"] == "STALE_PRE_SIGNAL_QUOTE"
    assert row["reference_age_ms"] > row["max_reference_lag_ms"]
    assert row["liquidatable_net"] is False
    assert summarize_executable_episodes([row])["positions_fermees"] == 0


def test_episode_refuse_une_sortie_observee_trop_tard():
    hl = [
        (5_000_000, 100.0, 99.99, 100.01, 10.0, 10.0),
        (15_000_000, 100.1, 100.09, 100.11, 10.0, 10.0),
        (60_000_000_000, 100.5, 100.49, 100.51, 10.0, 10.0),
    ]
    row = episodes_par_horizon(
        hl,
        [(10_000_000, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=[100.0],
    )[100.0][0]

    assert row["exit_status"] == "STALE_EXIT_QUOTE"
    assert row["exit_observation_lag_ms"] > row["max_exit_lag_ms"]
    assert row["liquidatable_net"] is False


def test_episode_borne_la_fraicheur_par_l_horizon_economique():
    hl = [
        (0, 100.0, 99.99, 100.01, 10.0, 10.0),
        (250_000_000, 100.1, 100.09, 100.11, 10.0, 10.0),
        (700_000_000, 100.2, 100.19, 100.21, 10.0, 10.0),
    ]
    row = episodes_par_horizon(
        hl,
        [(200_000_000, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=[100.0],
        max_reference_lag_ms=30_000.0,
        max_exit_lag_ms=30_000.0,
    )[100.0][0]

    assert row["configured_max_reference_lag_ms"] == 30_000.0
    assert row["configured_max_exit_lag_ms"] == 30_000.0
    assert row["max_reference_lag_ms"] == 100.0
    assert row["max_exit_lag_ms"] == 100.0
    assert row["reference_status"] == "STALE_PRE_SIGNAL_QUOTE"
    assert row["exit_status"] == "STALE_EXIT_QUOTE"
    assert row["liquidatable_net"] is False


def test_executable_campaign_separe_oos_et_vrai_forward_post_freeze():
    rows = _rows(30)
    tape = {"ETH": {"HL": [], "BIN": [], "TRADE": []}}
    for row in rows:
        timestamp = int(row["recu_ns"])
        if row["venue"] == "HL":
            tape["ETH"]["HL"].append(
                (
                    timestamp,
                    row["mid"],
                    row["bid"],
                    row["ask"],
                    row["bid_sz"],
                    row["ask_sz"],
                )
            )
        else:
            tape["ETH"]["TRADE"].append(
                (timestamp, row["px"], 1.0 if row["side"] == "BUY" else -1.0)
            )
    evidence = executable_campaign_evidence(
        tape,
        frozen_at_ms=20_500,
        horizon_ms=100.0,
        frais_slippage_bps=9.0,
        notional_usd=25.0,
    )

    assert evidence["summary"]["economic_reconciliation_ok"] is True
    assert evidence["summary"]["duplicate_trade_ids"] == 0
    assert evidence["segment_summaries"]["oos"]["positions_fermees"] > 0
    assert evidence["segment_summaries"]["forward"]["positions_fermees"] > 0
    assert evidence["temporal_evidence"]["oos"]["no_lookahead"] is True
    assert evidence["temporal_evidence"]["forward"]["post_freeze"] is True
    assert all(
        row["walk_forward_segment"] in {"train", "validation", "oos", "forward"}
        for row in evidence["trades"]
    )


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
                         "mid": mid, "bid": mid * 0.9999, "ask": mid * 1.0001,
                         "bid_sz": 10.0, "ask_sz": 10.0})
        px = px_haut                                                  # CONTINU : le bloc suivant repart d'ici
    return rows


def _tape_from_rows(rows):
    tape = {"ETH": {"HL": [], "BIN": [], "TRADE": []}}
    for row in rows:
        timestamp = int(row["recu_ns"])
        if row["venue"] == "HL":
            tape["ETH"]["HL"].append(
                (
                    timestamp,
                    row["mid"],
                    row["bid"],
                    row["ask"],
                    row["bid_sz"],
                    row["ask_sz"],
                )
            )
        else:
            tape["ETH"]["TRADE"].append(
                (timestamp, row["px"], 1.0 if row["side"] == "BUY" else -1.0)
            )
    return tape


def test_freeze_readiness_refuse_un_historique_vide_sans_creer_de_preuve():
    readiness = calibrate_freeze_readiness({})

    assert readiness["selection_eligible"] is False
    assert readiness["status"] == "INSUFFICIENT_HISTORY_NO_OBSERVATION"
    assert readiness["provisional_frozen_at_ms"] is None
    assert readiness["selection_basis"] == "STRUCTURE_ONLY_NO_PNL"


def test_freeze_readiness_ne_selectionne_que_sur_la_structure_des_segments():
    readiness = calibrate_freeze_readiness(
        _tape_from_rows(_rows(40)),
        horizon_ms=100.0,
        frais_slippage_bps=9.0,
        min_liquidatable_observations=30,
    )

    assert readiness["selection_eligible"] is True
    assert readiness["status"] == "ELIGIBLE_TO_FREEZE"
    assert readiness["liquidatable_observations"] >= 30
    assert all(count > 0 for count in readiness["segment_counts"].values())
    assert readiness["pnl_fields_read_for_selection"] == []


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


def test_charger_tape_historique_utilise_horloge_murale_et_dedupe(tmp_path):
    data = tmp_path / "runtime" / "data"
    shards = data / "bbo_shards"
    shards.mkdir(parents=True)
    current = data / "bbo_tape.jsonl"
    duplicate = {
        "event_id": "trade-unique",
        "venue": "BIN_TRADE",
        "coin": "ETH",
        "recu_ns": 9_000_000_000,
        "ts_wall_ms": 2_000,
        "px": 101.0,
        "side": "BUY",
    }
    current.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                duplicate,
                {
                    "event_id": "hl-new",
                    "venue": "HL",
                    "coin": "ETH",
                    "recu_ns": 1,
                    "ts_wall_ms": 2_100,
                    "mid": 101.0,
                    "bid": 100.9,
                    "ask": 101.1,
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    historical = shards / "bbo_tape_00000000000000001000.jsonl.gz"
    with gzip.open(historical, "wt", encoding="utf-8") as handle:
        for row in (
            {
                "event_id": "hl-old",
                "venue": "HL",
                "coin": "ETH",
                # A process-local monotonic clock can restart above/below any
                # prior process.  Wall time must therefore win the ordering.
                "recu_ns": 99_000_000_000,
                "ts_wall_ms": 1_000,
                "mid": 100.0,
                "bid": 99.9,
                "ask": 100.1,
            },
            duplicate,
        ):
            handle.write(json.dumps(row) + "\n")

    sources = selectionner_sources(tmp_path, include_history=True, max_history_sources=1)
    assert sources == [current, historical]
    tape, meta = charger_tape(tmp_path, sources=sources, return_meta=True)

    assert [row[1] for row in tape["ETH"]["HL"]] == [100.0, 101.0]
    assert len(tape["ETH"]["TRADE"]) == 1
    assert meta["duplicates_rejected"] == 1
    assert meta["sources_count"] == 2
    assert meta["timestamp_clock"].startswith("ts_wall_ms")


def test_geler_config_ecrit_un_rejet_complet_quand_la_preuve_manque(tmp_path):
    cfg = geler_config(tmp_path, coins=["ETH", "SOL"], coins_controle=["DOGE"], horizons_ms=[100.0, 500.0])
    assert (tmp_path / CONFIG_GELE).exists()
    assert cfg["schema_version"] == SCHEMA_VERSION
    assert cfg["coins"] == ["ETH", "SOL"] and cfg["control_coins"] == ["DOGE"]
    assert cfg["requested_horizons_ms"] == [100.0, 500.0]
    assert cfg["promotion_status"] == "REJECTED"
    assert set(cfg["criteria"])
    with pytest.raises(FrozenLeadLagEvidenceError, match="EVIDENCE_NOT_PROMOTED"):
        validate_frozen_evidence(cfg)


def test_walk_forward_protocol_signature_excludes_growing_dataset_shape():
    signature = walk_forward_protocol_signature()

    assert signature["execution_model"] == CAMPAIGN_EXECUTION_MODEL
    assert signature["economic_horizon_ms"] == CAMPAIGN_HORIZON_MS
    assert signature["minimum_shocks"] > 0
    assert signature["freshness_cap_policy"].startswith("min(")
    assert signature["freeze_readiness_policy"].startswith("static_params")
    assert "history_sources" not in signature
    assert "dataset_fingerprint" not in signature


def test_geler_config_promotes_only_complete_robust_evidence(tmp_path):
    evidence = {
        "statut": "PROMETTEUR",
        "horizons_observables": [1000.0],
        "net_par_horizon": {
            1000.0: {
                "esperance_nette_bps": 12.0,
                "n": 40,
                "stable": True,
                "bootstrap_mean_ci95_bps": [3.0, 20.0],
            }
        },
        "controle_par_horizon": {1000.0: -1.0},
        "placebo_par_horizon": {1000.0: 0.5},
        "dsr_par_horizon": {1000.0: {"survit": True}},
        "pbo": {"pbo": 0.25, "verdict": "ROBUSTE"},
        "frequence_evenements_par_jour": 4.0,
        "alpha_half_life_p95_ms": 2_000.0,
        "end_to_end_latency_p95_ms": 100.0,
        "latency_safety_margin_ms": 25.0,
        "information_coefficient": {"value": None, "status": "UNMEASURABLE"},
        "regimes": {"stable_horizons_ms": [1000.0]},
    }
    cfg = geler_config(
        tmp_path,
        coins=["ETH"],
        coins_controle=["DOGE"],
        horizons_ms=[1000.0],
        evidence=evidence,
    )
    assert cfg["promotion_status"] == "PROMOTED"
    normalized = validate_frozen_evidence(cfg)
    assert normalized["edge_net_par_horizon_bps"][1000.0] == 12.0
    assert normalized["sample_n_by_horizon"][1000.0] == 40
    assert normalized["latency_budget"]["remaining_budget_ms"] == 1_875.0


def test_clock_boundary_trials_are_global_and_idempotent(tmp_path):
    kwargs = {
        "coins": ["ETH"],
        "coins_controle": ["DOGE"],
        "horizons_ms": [50.0, 100.0, 250.0, 500.0, 1000.0],
    }
    first = geler_config(tmp_path, **kwargs)
    second = geler_config(tmp_path, **kwargs)
    ledger = tmp_path / GLOBAL_TRIAL_LEDGER
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 5
    assert first["global_trials"]["added"] == 5
    assert second["global_trials"]["added"] == 0
    assert second["global_trials"]["count"] == 5


def test_legacy_frozen_parameters_are_not_runtime_evidence():
    with pytest.raises(FrozenLeadLagEvidenceError, match="UNSUPPORTED_SCHEMA"):
        validate_frozen_evidence(
            {
                "coins": ["ETH"],
                "horizons_ms": [1000],
                "edge_net_par_horizon_bps": {"1000": 10},
            }
        )


def test_exact_frozen_producer_contract_is_consumed_by_runtime(tmp_path):
    now_ms = 1_000_000.0
    tape = tmp_path / "runtime" / "data" / "bbo_tape.jsonl"
    tape.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "venue": "HL",
            "coin": "ETH",
            "recu_ns": 1,
            "recv_wall_ts_ms": now_ms - 100,
            "bid": 99.99,
            "ask": 100.01,
            "mid": 100.0,
        },
        {
            "venue": "BIN_TRADE",
            "coin": "ETH",
            "recu_ns": 2,
            "recv_wall_ts_ms": now_ms - 50,
            "px": 100.5,
            "side": "BUY",
        },
    ]
    tape.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    evidence = {
        "statut": "PROMETTEUR",
        "horizons_observables": [1000.0],
        "net_par_horizon": {
            1000.0: {
                "esperance_nette_bps": 12.0,
                "n": 40,
                "stable": True,
                "bootstrap_mean_ci95_bps": [3.0, 20.0],
            }
        },
        "controle_par_horizon": {1000.0: -1.0},
        "placebo_par_horizon": {1000.0: 0.5},
        "dsr_par_horizon": {1000.0: {"survit": True}},
        "pbo": {"pbo": 0.25},
        "frequence_evenements_par_jour": 4.0,
        "alpha_half_life_p95_ms": 2_000.0,
        "end_to_end_latency_p95_ms": 100.0,
        "latency_safety_margin_ms": 25.0,
    }
    geler_config(
        tmp_path,
        coins=["ETH"],
        coins_controle=["DOGE"],
        horizons_ms=[1000.0],
        evidence=evidence,
    )
    signals, refusals = signaux_lead_lag(tmp_path, now_ms=now_ms)
    assert not refusals
    assert len(signals) == 1
    assert signals[0].coin == "ETH"
    assert signals[0].edge_estime_bps > 0

from __future__ import annotations

from copy import deepcopy

from tools.copy_vault_discovery_evaluator import _enrich, evaluate_feature_rows


def _rows() -> list[dict]:
    day = 86_400_000
    rows = []
    for index in range(12):
        rows.append(
            {
                "trade_id": f"t{index}",
                "walk_forward_segment": "train",
                "signal_ts_ms": 1_800_000_000_000 + index * day,
                "vault": f"v{index % 4}",
                "coin": "ETH" if index % 2 else "SOL",
                "direction": 1,
                "net_pnl_usd": float(index - 3),
                "gross_pnl_usd": float(index - 2),
                "fees_usd": 0.5,
                "spread_cost_usd": 0.25,
                "slippage_cost_usd": 0.15,
                "latency_cost_usd": 0.10,
                "notional_usd": 100.0,
                "entry_capacity_usd": 500.0 + index * 100,
                "exit_capacity_usd": 600.0 + index * 100,
                "observed_latency_ms": 12_000 - index * 500,
                "reference_lag_ms": 2_000 + index,
                "regime_reference_spread_bps": 8.0 - index * 0.2,
                "feature_fill_count": 2 + index,
                "feature_burst_rate_hz": 0.1 + index * 0.1,
                "feature_size_acceleration": 0.5 + index * 0.1,
                "feature_prior_consensus": index % 5,
                "feature_rotation": bool(index % 3 == 0),
            }
        )
    return rows


def test_feature_selection_ne_lit_pas_le_pnl() -> None:
    rows = _rows()
    first = evaluate_feature_rows(
        rows,
        mechanism="BURST_ACCELERATION",
        keep_fraction=0.5,
        family_trial_count=24,
    )
    changed = deepcopy(rows)
    for index, row in enumerate(changed):
        row["net_pnl_usd"] = 10_000.0 if index % 2 else -10_000.0
        row["gross_pnl_usd"] = row["net_pnl_usd"] + 1.0
    second = evaluate_feature_rows(
        changed,
        mechanism="BURST_ACCELERATION",
        keep_fraction=0.5,
        family_trial_count=24,
    )

    assert first["selected_trade_ids"] == second["selected_trade_ids"]
    assert first["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert first["candidate_verdict"] != "FREEZE_CANDIDATE"


def test_tournament_expose_headroom_et_concentration_sans_certifier() -> None:
    result = evaluate_feature_rows(
        _rows(),
        mechanism="CAPACITY_SLACK",
        keep_fraction=0.75,
        family_trial_count=24,
    )

    assert result["sample_count"] == 9
    assert result["distinct_days"] == 9
    assert result["net_usd"] > 0.0
    assert result["daily_net_usd"] is not None
    assert result["family_trial_count"] == 24
    assert 0.0 <= result["largest_vault_share"] <= 1.0
    assert result["candidate_verdict"] in {"ITERATE", "REJECT"}


def test_feature_absente_echoue_ferme() -> None:
    rows = _rows()
    for row in rows:
        row.pop("feature_prior_consensus")

    result = evaluate_feature_rows(
        rows,
        mechanism="INDEPENDENT_CONSENSUS",
        keep_fraction=0.5,
        family_trial_count=24,
    )

    assert result["candidate_verdict"] == "REJECT"
    assert "FEATURE_UNAVAILABLE" in result["candidate_reasons"]


def test_entry_features_ne_lisent_pas_la_capacite_de_sortie_future() -> None:
    base = _rows()[0]
    low_exit = _enrich([{**base, "exit_capacity_usd": 1.0}])[0]
    high_exit = _enrich([{**base, "exit_capacity_usd": 1_000_000.0}])[0]

    assert low_exit["feature_execution_efficiency"] == high_exit[
        "feature_execution_efficiency"
    ]
    assert low_exit["feature_l2_state_quality"] == high_exit[
        "feature_l2_state_quality"
    ]

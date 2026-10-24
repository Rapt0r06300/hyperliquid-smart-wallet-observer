from __future__ import annotations

import copy

import pytest

from hl_observer.backtesting import copy_vault_v21_frozen as V21
from hl_observer.backtesting.copy_vault_protocol import MAX_GROSS_EXPOSURE_USD
from hl_observer.simulation.economic_freeze_registry import parameter_hash


def _freeze() -> dict:
    params = {
        "protocol": V21.PROTOCOL,
        "training_selection_eligible": True,
        "paper_read_only": True,
        "real_execution": False,
        "minimum_leader_fill_notional_usd": 100.0,
        "signed_depth_imbalance_minimum": 0.0,
        "core_notional_usd": 150.0,
        "probe_notional_usd": 75.0,
        "daily_profit_lock_usd": 4.0,
        "stop_loss_bps": 50.0,
        "take_profit_bps": 100.0,
        "horizon_ms": 3_600_000,
        "vault_daily_limit": 1,
        "coin_daily_limit": 1,
        "max_open_positions": 10,
        "bonferroni_trial_count": 432,
        "bounds": {
            "train_start_ms": 100,
            "train_end_ms": 900,
            "validation_start_ms": 1_000,
            "validation_end_ms": 2_000,
            "oos_start_ms": 3_000,
            "oos_end_ms": 4_000,
        },
    }
    return {
        "freeze": {
            "schema_version": "hypersmart.economic_parameter_freeze.v1",
            "campaign_id": "frozen",
            "family": "copy_vault",
            "frozen_at_ms": 5_000,
            "selected_before_final_evaluation": True,
            "parameters": params,
            "parameters_sha256": parameter_hash(params),
            "dataset_provenance": {},
        }
    }


def _segment(name: str, eligible: bool) -> dict:
    return {
        "segment": name,
        "status": "PASS" if eligible else "FAIL",
        "eligible": eligible,
        "heldout_evaluated": True,
        "retuned_on_heldout": False,
        "paper_read_only": True,
        "real_execution": False,
        "carry_pnl_usd": 0.0,
    }


def test_reference_depth_uses_only_the_latest_book_received_by_signal_time() -> None:
    books = [
        {
            "ts_ms": 990,
            "causal_observation": True,
            "bids5": [[100.0, 2.0]],
            "asks5": [[101.0, 1.0]],
        },
        {
            "ts_ms": 1_001,
            "causal_observation": True,
            "bids5": [[100.0, 1.0]],
            "asks5": [[101.0, 2.0]],
        },
    ]

    candidates, audit = V21._segment_candidates(
        [
            {
                "signal_ts_ms": 1_000,
                "direction": 1,
                "coin": "BTC",
                "member_events": [{"action": "ADD", "taille_usd": 150.0}],
            }
        ],
        {"BTC": books},
        start_ms=900,
        end_ms=1_200,
        minimum_leader_fill_notional_usd=100.0,
        signed_depth_imbalance_minimum=-1.0,
    )

    assert len(candidates) == 1
    assert candidates[0]["signed_reference_depth_imbalance"] == pytest.approx(99.0 / 301.0)
    assert candidates[0]["reference_two_sided_capacity_usd"] == pytest.approx(101.0)
    assert audit["FIXED_POLICY_CANDIDATE"] == 1


def test_reference_depth_is_unmeasurable_without_a_pre_signal_book() -> None:
    future_only = [
        {
            "ts_ms": 1_001,
            "causal_observation": True,
            "bids5": [[100.0, 2.0]],
            "asks5": [[101.0, 1.0]],
        }
    ]

    candidates, audit = V21._segment_candidates(
        [
            {
                "signal_ts_ms": 1_000,
                "direction": 1,
                "coin": "BTC",
                "member_events": [{"action": "ADD", "taille_usd": 150.0}],
            }
        ],
        {"BTC": future_only},
        start_ms=900,
        end_ms=1_200,
        minimum_leader_fill_notional_usd=100.0,
        signed_depth_imbalance_minimum=-1.0,
    )

    assert candidates == []
    assert audit["REFERENCE_DEPTH_FEATURE_UNMEASURABLE"] == 1


def test_reference_depth_rejects_stale_or_noncausal_books() -> None:
    stale = {
        "ts_ms": 100_000,
        "causal_observation": True,
        "bids5": [[100.0, 2.0]],
        "asks5": [[101.0, 1.0]],
    }
    historical = {
        **stale,
        "ts_ms": 130_001,
        "causal_observation": False,
    }

    assert V21._reference_depth_features(
        {"signal_ts_ms": 130_002, "direction": 1}, [stale]
    ) is None
    assert V21._reference_depth_features(
        {"signal_ts_ms": 130_002, "direction": 1}, [historical]
    ) is None


@pytest.mark.parametrize(
    "book",
    [
        {
            "ts_ms": 1_000, "causal_observation": True,
            "bids5": [[100.0, float("nan")]], "asks5": [[101.0, 1.0]],
        },
        {
            "ts_ms": 1_000, "causal_observation": True,
            "bids5": [[100.0, 1.0]], "asks5": [[float("inf"), 1.0]],
        },
        {
            "ts_ms": 1_000, "causal_observation": True,
            "bids5": [[100.0, -1.0]], "asks5": [[101.0, 1.0]],
        },
    ],
)
def test_reference_depth_refuse_les_niveaux_non_economiques(book) -> None:
    assert V21._reference_depth_features(
        {"signal_ts_ms": 1_000, "direction": 1}, [book]
    ) is None


@pytest.mark.parametrize("notional", [None, True, float("nan"), float("inf"), -1.0])
def test_segment_refuse_un_premier_fill_non_mesurable(notional) -> None:
    candidates, audit = V21._segment_candidates(
        [{
            "signal_ts_ms": 1_000,
            "direction": 1,
            "coin": "BTC",
            "member_events": [{"action": "ADD", "taille_usd": notional}],
        }],
        {"BTC": [{
            "ts_ms": 1_000,
            "causal_observation": True,
            "bids5": [[100.0, 2.0]],
            "asks5": [[101.0, 1.0]],
        }]},
        start_ms=900,
        end_ms=1_200,
        minimum_leader_fill_notional_usd=100.0,
        signed_depth_imbalance_minimum=-1.0,
    )

    assert candidates == []
    assert audit["LEADER_FILL_NOTIONAL_UNMEASURABLE"] == 1


def test_frozen_v21_opens_heldouts_sequentially(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake(*_args, segment: str, **_kwargs):
        calls.append(segment)
        return _segment(segment, segment == "validation")

    monkeypatch.setattr(V21, "_evaluate_segment", fake)
    report = V21.evaluate_frozen_v21([], {}, _freeze())

    assert calls == ["validation", "oos"]
    assert report["validation"]["eligible"] is True
    assert report["oos"]["eligible"] is False
    assert report["forward"]["status"] == "BLOCKED_BY_OOS"
    assert report["forward"]["heldout_evaluated"] is False
    assert report["objective_status"] == "UNMEASURABLE"
    assert report["carry_pnl_usd"] == 0.0


def test_segment_calendar_coverage_does_not_discard_malformed_day_entries() -> None:
    params = _freeze()["freeze"]["parameters"]
    result = V21._evaluate_segment(
        [],
        {},
        segment="validation",
        start_ms=0,
        end_ms=2 * 86_400_000,
        params=params,
        complete_utc_day_starts_ms=[0, 86_400_000, "malformed"],
    )

    assert result["calendar_day_statistics"]["status"] == "UNMEASURABLE"
    assert (
        result["calendar_day_statistics"]["reason"]
        == "INVALID_COMPLETE_UTC_DAY_COVERAGE"
    )


def test_calendar_pnl_is_attributed_to_trade_close_utc_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = 86_400_000
    monkeypatch.setattr(V21, "_segment_candidates", lambda *_args, **_kwargs: ([], {}))
    monkeypatch.setattr(
        V21,
        "_settle",
        lambda *_args, **_kwargs: (
            [{"net_pnl_usd": 7.0, "entry_ts_ms": day - 1, "exit_ts_ms": day}],
            [],
            {},
        ),
    )
    monkeypatch.setattr(
        V21,
        "assess_train_variant",
        lambda *_args, **_kwargs: {
            "statistics": {"daily_net_pnl_usd": [7.0]},
            "reasons": [],
        },
    )

    result = V21._evaluate_segment(
        [],
        {},
        segment="validation",
        start_ms=0,
        end_ms=2 * day - 1,
        params=_freeze()["freeze"]["parameters"],
        complete_utc_day_starts_ms=[0, day],
    )

    assert result["calendar_day_statistics"]["calendar_day_net_pnl_usd"] == [
        0.0,
        7.0,
    ]


def test_frozen_v21_never_opens_oos_after_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake(*_args, segment: str, **_kwargs):
        calls.append(segment)
        return _segment(segment, False)

    monkeypatch.setattr(V21, "_evaluate_segment", fake)
    report = V21.evaluate_frozen_v21([], {}, _freeze())

    assert calls == ["validation"]
    assert report["oos"]["status"] == "BLOCKED_BY_VALIDATION"
    assert report["oos"]["heldout_evaluated"] is False
    assert report["forward"]["heldout_evaluated"] is False


def test_forward_eligible_evaluation_wires_capacity_and_stress_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        V21,
        "_evaluate_segment",
        lambda *_args, segment, **_kwargs: _segment(segment, True),
    )

    report = V21.evaluate_frozen_v21([], {}, _freeze())

    assert report["economically_proven"] is True
    assert report["capacity_diagnostic"]["capital_scenarios_usd"] == [
        10.0,
        50.0,
        100.0,
        200.0,
        400.0,
        1_000.0,
        2_000.0,
        5_000.0,
        10_000.0,
    ]
    assert report["capacity_diagnostic"]["promotion_eligible"] is False
    assert report["stress_diagnostic"]["scenario_count"] == 13
    assert report["stress_diagnostic"]["promotion_eligible"] is False


def test_frozen_v21_rejects_parameter_tampering() -> None:
    payload = _freeze()
    tampered = copy.deepcopy(payload)
    tampered["freeze"]["parameters"]["core_notional_usd"] = 999.0
    with pytest.raises(ValueError, match="FREEZE_HASH_MISMATCH"):
        V21.evaluate_frozen_v21([], {}, tampered)


def test_frozen_v21_rejects_single_trade_notional_above_paper_gross_limit() -> None:
    payload = _freeze()
    params = payload["freeze"]["parameters"]
    params["core_notional_usd"] = MAX_GROSS_EXPOSURE_USD + 0.01
    payload["freeze"]["parameters_sha256"] = parameter_hash(params)

    with pytest.raises(ValueError, match="PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED"):
        V21.evaluate_frozen_v21([], {}, payload)


def test_frozen_v21_rejects_incomplete_hashed_parameters_before_evaluation() -> None:
    payload = _freeze()
    params = payload["freeze"]["parameters"]
    del params["horizon_ms"]
    payload["freeze"]["parameters_sha256"] = parameter_hash(params)

    with pytest.raises(ValueError, match="COPY_V21_FREEZE_PARAMETERS_INVALID"):
        V21.evaluate_frozen_v21([], {}, payload)


def test_frozen_v21_rejects_non_chronological_hashed_bounds() -> None:
    payload = _freeze()
    params = payload["freeze"]["parameters"]
    params["bounds"]["oos_start_ms"] = params["bounds"]["validation_end_ms"]
    payload["freeze"]["parameters_sha256"] = parameter_hash(params)

    with pytest.raises(ValueError, match="COPY_V21_FREEZE_BOUNDS_INVALID"):
        V21.evaluate_frozen_v21([], {}, payload)


def test_settle_rejects_overlapping_positions_above_paper_gross_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float] = []

    def execute(_metaorder, _books, *, notional_usd: float, **_kwargs):
        calls.append(notional_usd)
        signal_ms = int(_metaorder["signal_ts_ms"])
        return (
            {
                "entry_ts_ms": signal_ms + 1,
                "exit_ts_ms": signal_ms + 300_000,
                "direction": 1,
                "quantity": 1.0,
                "entry_price": 100.0,
                "notional_usd": notional_usd,
                "net_pnl_usd": -1.0,
            },
            "LIQUIDATABLE_NET",
        )

    monkeypatch.setattr(V21.cv, "execute_metaorder", execute)
    params = {
        "horizon_ms": 300_000,
        "vault_daily_limit": 10,
        "coin_daily_limit": 10,
        "max_open_positions": 10,
        "daily_profit_lock_usd": 4.0,
        "core_notional_usd": 150.0,
        "probe_notional_usd": 75.0,
        "stop_loss_bps": 50.0,
        "take_profit_bps": 100.0,
    }
    candidates = [
        {
            "signal_ts_ms": 1_000 + index * 1_000,
            "metaorder_id": f"meta-{index}",
            "vault": f"vault-{index}",
            "coin": "BTC",
            "direction": 1,
            "signed_reference_depth_imbalance": 0.2,
            "reference_two_sided_capacity_usd": 1_000.0,
        }
        for index in range(2)
    ]

    trades, _placebos, audit = V21._settle(
        candidates, {"BTC": []}, segment="validation", params=params
    )

    assert len(trades) == 1
    assert calls == [150.0, 150.0]
    assert audit["PAPER_GROSS_EXPOSURE_REJECTED"] == 1


def test_capacity_scenario_scales_frozen_sizing_but_remains_diagnostic_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float] = []

    def execute(_metaorder, _books, *, notional_usd: float, **_kwargs):
        calls.append(notional_usd)
        signal_ms = int(_metaorder["signal_ts_ms"])
        return (
            {
                "entry_ts_ms": signal_ms + 1,
                "exit_ts_ms": signal_ms + 300_000,
                "direction": 1,
                "quantity": 1.0,
                "entry_price": 100.0,
                "notional_usd": notional_usd,
                "net_pnl_usd": -1.0,
            },
            "LIQUIDATABLE_NET",
        )

    monkeypatch.setattr(V21.cv, "execute_metaorder", execute)
    params = {
        "horizon_ms": 300_000,
        "vault_daily_limit": 10,
        "coin_daily_limit": 10,
        "max_open_positions": 10,
        "daily_profit_lock_usd": 4.0,
        "core_notional_usd": 150.0,
        "probe_notional_usd": 75.0,
        "stop_loss_bps": 50.0,
        "take_profit_bps": 100.0,
    }
    candidate = {
        "signal_ts_ms": 1_000,
        "metaorder_id": "meta-0",
        "vault": "vault-0",
        "coin": "BTC",
        "direction": 1,
        "signed_reference_depth_imbalance": 0.2,
        "reference_two_sided_capacity_usd": 1_000.0,
    }

    trades, _placebos, audit = V21._settle(
        [candidate],
        {"BTC": []},
        segment="capacity_400",
        params=params,
        capital_scenario_usd=400.0,
    )

    assert calls == [300.0, 300.0]
    assert trades[0]["notional_usd"] == 300.0
    assert trades[0]["economic_scope"] == "DIAGNOSTIC_ONLY"
    assert trades[0]["economically_proven"] is False
    assert audit.get("PAPER_GROSS_EXPOSURE_REJECTED", 0) == 0


def test_capacity_scenarios_use_the_predeclared_ladder_and_never_certify() -> None:
    result = V21.evaluate_capacity_scenarios([], {}, _freeze())

    assert result["capital_scenarios_usd"] == [
        10.0,
        50.0,
        100.0,
        200.0,
        400.0,
        1_000.0,
        2_000.0,
        5_000.0,
        10_000.0,
    ]
    assert result["scope"] == "DIAGNOSTIC_ONLY"
    assert result["economic_proof"] is False
    assert result["promotion_eligible"] is False
    assert all(row["economically_proven"] is False for row in result["scenarios"])


@pytest.mark.parametrize("scenarios", [[], [0.0], [float("nan")], [10.0, 10.0]])
def test_capacity_scenarios_reject_invalid_capital_ladders(scenarios) -> None:
    with pytest.raises(ValueError, match="COPY_V21_CAPITAL_SCENARIOS_INVALID"):
        V21.evaluate_capacity_scenarios(
            [], {}, _freeze(), capital_scenarios_usd=scenarios
        )


def test_stress_books_widen_spread_and_reduce_depth_without_mutating_input() -> None:
    source = {
        "BTC": [
            {
                "ts_ms": 1_000,
                "bid": 100.0,
                "ask": 102.0,
                "bids5": [[100.0, 2.0]],
                "asks5": [[102.0, 3.0]],
                "causal_observation": True,
            }
        ]
    }

    stressed = V21._stress_books(
        source, spread_multiplier=2.0, depth_multiplier=0.5
    )

    assert stressed["BTC"][0]["bids5"] == [[99.0, 1.0]]
    assert stressed["BTC"][0]["asks5"] == [[103.0, 1.5]]
    assert source["BTC"][0]["bids5"] == [[100.0, 2.0]]
    assert source["BTC"][0]["asks5"] == [[102.0, 3.0]]


def test_stress_matrix_is_predeclared_diagnostic_and_lists_unmeasured_axes() -> None:
    result = V21.evaluate_stress_matrix([], {}, _freeze())

    assert result["scenario_count"] == 13
    assert result["scope"] == "DIAGNOSTIC_ONLY"
    assert result["economic_proof"] is False
    assert result["promotion_eligible"] is False
    assert result["scenarios"][0]["scenario"] == "BASELINE_REFERENCE"
    assert result["scenarios"][1]["scenario"] == "FEE_X2"
    assert result["scenarios"][2]["scenario"] == "SPREAD_X2"
    assert result["scenarios"][-1]["scenario"] == "EXTRA_DELAY_300000MS"
    assert result["not_evaluated"]["funding_adverse"] == (
        "UNMEASURABLE_FUNDING_ROWS_NOT_WIRED"
    )


def test_stress_matrix_runs_the_real_causal_l2_executor_and_records_delay_refusals() -> None:
    payload = _freeze()
    params = payload["freeze"]["parameters"]
    params["horizon_ms"] = 300_000
    params["stop_loss_bps"] = 5_000.0
    params["take_profit_bps"] = 5_000.0
    payload["freeze"]["parameters_sha256"] = parameter_hash(params)
    signal_ms = 6_000
    books = [
        {
            "ts_ms": ts_ms,
            "bid": 100.0,
            "ask": 101.0,
            "capacity_usd": 2_500.0,
            "bids5": [[100.0, 21.0]],
            "asks5": [[101.0, 20.0]],
            "causal_observation": True,
            "source_line": index + 1,
        }
        for index, ts_ms in enumerate(
            (signal_ms, signal_ms + 60_000, signal_ms + 360_000)
        )
    ]
    metaorders = [
        {
            "metaorder_id": "stress-metaorder",
            "vault": "vault-stress",
            "coin": "BTC",
            "direction": 1,
            "signal_ts_ms": signal_ms,
            "member_events": [{"action": "ADD", "taille_usd": 150.0}],
        }
    ]

    result = V21.evaluate_stress_matrix(
        metaorders, {"BTC": books}, payload, segment="forward"
    )

    baseline = result["scenarios"][0]["result"]
    fee_stress = result["scenarios"][1]["result"]
    assert fee_stress["candidate_count"] == 1
    assert fee_stress["replay_audit"]["ADMITTED_CLOSED_POSITION"] == 1
    assert (
        fee_stress["economic_summary"]["net_pnl_usd"]
        < baseline["economic_summary"]["net_pnl_usd"]
    )
    delay_300s = result["scenarios"][-1]["result"]
    assert delay_300s["candidate_count"] == 1
    assert delay_300s["replay_audit"]["INCOMPLETE_EPISODE_REJECTED"] == 1
    assert delay_300s["replay_audit"]["ACTUAL_PROVENANCE_REFUSAL_STALE_OR_MISSING_EXIT_BOOK"] == 1


def test_frozen_v21_does_not_use_the_five_dollar_reference_as_a_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        V21,
        "_segment_candidates",
        lambda *_args, **_kwargs: ([{"signal_ts_ms": 1_500}], {}),
    )
    monkeypatch.setattr(
        V21,
        "_settle",
        lambda *_args, **_kwargs: ([], [], {}),
    )
    monkeypatch.setattr(
        V21,
        "assess_train_variant",
        lambda *_args, **_kwargs: {
            "statistics": {"daily_net_pnl_usd": [4.5]},
            "reasons": [],
        },
    )

    result = V21._evaluate_segment(
        [],
        {},
        segment="validation",
        start_ms=1_000,
        end_ms=2_000,
        params={
            "daily_profit_lock_usd": 4.0,
            "bonferroni_trial_count": 432,
            "minimum_leader_fill_notional_usd": 100.0,
            "signed_depth_imbalance_minimum": 0.0,
        },
    )

    assert result["eligible"] is True
    assert "DAILY_MEAN_NET_BELOW_5_USD" not in result["reasons"]
    assert result["status"] == "PASS"


def test_reference_objective_status_is_independent_from_economic_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        V21,
        "_evaluate_segment",
        lambda *_args, segment, **_kwargs: {
            "segment": segment,
            "eligible": True,
            "daily_mean_net_pnl_usd": 4.5,
        },
    )

    report = V21.evaluate_frozen_v21([], {}, _freeze())

    assert report["economically_proven"] is True
    assert report["objective_status"] == "NON_ATTEINT"
    assert report["objective_is_informational_reference_only"] is True

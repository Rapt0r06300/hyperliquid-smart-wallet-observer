from __future__ import annotations

import json
import math
from decimal import Decimal, localcontext
from random import Random

from scipy.special import ndtri

from hl_observer.backtesting.train_statistics import (
    _certified_normal_critical_value_upper_bound,
    _normal_tail_upper_bound,
    exact_lcb_rank_value,
    exact_net_rank_value,
    lcb_rank_is_numerically_resolved,
    profit_factor,
    select_unambiguous_lcb_candidate,
    stable_hash,
    summarize_complete_utc_days,
    summarize_daily_values,
    summarize_train_rows,
    top_positive_share,
    top_positive_share_within_limit,
)
from hl_observer.economics.numeric import float_not_above, float_not_below


def test_bonferroni_lcb_reste_strictement_train_et_positif_sur_jours_stables() -> None:
    day = 86_400_000
    rows = [
        {"ts": day * index, "net": 1.0}
        for index in range(1, 6)
    ]
    result = summarize_train_rows(
        rows,
        value_key="net",
        timestamp_key="ts",
        trial_count=10,
    )

    assert result["sample_count"] == 5
    assert result["distinct_days"] == 5
    assert result["bonferroni_trial_count"] == 10
    assert result["adjusted_one_sided_alpha"] == 0.005
    assert result["net_pnl_usd"] == 5.0
    # The exposed LCB is deliberately rounded downward by its recorded
    # arithmetic error bound, so stable equal daily PnL stays just below the
    # nominal value instead of overstating certainty.
    assert Decimal(result["daily_mean_lcb_usd_exact_decimal"]) <= Decimal("1")
    assert Decimal(result["daily_mean_lcb_usd_exact_decimal"]) > Decimal("0.99")
    assert Decimal(result["total_lcb_usd_exact_decimal"]) <= Decimal("5")
    assert Decimal(result["total_lcb_usd_exact_decimal"]) > Decimal("4.99")


def test_extreme_tail_quantile_avoids_one_minus_alpha_cancellation() -> None:
    result = summarize_daily_values(
        ["1", "2", "3"],
        trial_count=1,
        family_alpha=1e-12,
    )

    z_upper = Decimal(result["critical_z_upper_bound_exact_decimal"])
    alpha_exact = Decimal.from_float(result["adjusted_one_sided_alpha"])
    assert z_upper >= Decimal("7.0344838253011")
    assert _normal_tail_upper_bound(z_upper) <= alpha_exact


def test_certified_normal_quantile_upper_bound_covers_alpha_grid() -> None:
    minimum = math.log(1e-12)
    maximum = math.log(0.499999)
    for index in range(65):
        alpha = math.exp(minimum + (maximum - minimum) * index / 64)
        certified_upper = _certified_normal_critical_value_upper_bound(alpha)
        reference = -float(ndtri(alpha))
        assert certified_upper >= Decimal.from_float(reference)
        assert _normal_tail_upper_bound(certified_upper) <= Decimal.from_float(alpha)


def test_conservative_float_conversions_compare_exact_binary64_values() -> None:
    exact_tenth = Decimal("0.1")
    pnl_float = float_not_above(exact_tenth)
    cost_float = float_not_below(exact_tenth)

    assert pnl_float is not None and Decimal.from_float(pnl_float) <= exact_tenth
    assert cost_float is not None and Decimal.from_float(cost_float) >= exact_tenth
    assert pnl_float < 0.1
    assert Decimal.from_float(cost_float) > exact_tenth

    exactly_representable = Decimal("0.5")
    assert float_not_above(exactly_representable) == 0.5
    assert float_not_below(exactly_representable) == 0.5


def test_profit_factor_mixed_pnl_uses_win_loss_ratio() -> None:
    assert profit_factor([3.0, -1.0, 2.0, -1.0]) == 2.5


def test_profit_factor_does_not_hide_tiny_real_losses_as_zero() -> None:
    assert profit_factor(["0.00000000000000000001", "-0.00000000000000000001"]) == 1.0


def test_top_positive_share_rounds_toward_conservative_concentration() -> None:
    assert top_positive_share(
        [Decimal("0.50000000000000001"), Decimal("0.49999999999999999")]
    ) > 0.5


def test_concentration_gate_uses_exact_share_at_and_just_above_the_limit() -> None:
    day = 86_400_000
    at_limit = summarize_train_rows(
        [
            {"ts": day + 1, "net": 0.6},
            {"ts": day + 2, "net": 0.4},
        ],
        value_key="net",
        timestamp_key="ts",
        trial_count=1,
    )
    just_over = summarize_train_rows(
        [
            {"ts": day + 1, "net": 0.6, "net_exact_decimal": "0.60000000000000001"},
            {"ts": day + 2, "net": 0.4, "net_exact_decimal": "0.39999999999999999"},
        ],
        value_key="net",
        timestamp_key="ts",
        trial_count=1,
    )

    assert at_limit["top_positive_trade_share"] >= 0.6
    assert top_positive_share_within_limit(at_limit, Decimal("0.6")) is True
    assert top_positive_share_within_limit(just_over, Decimal("0.6")) is False


def test_exact_net_rank_breaks_ties_hidden_by_float_precision() -> None:
    rounded_same = 5.0
    better = {"net_pnl_usd": rounded_same, "net_pnl_usd_exact_decimal": "5.0000000000000002"}
    worse = {"net_pnl_usd": rounded_same, "net_pnl_usd_exact_decimal": "5.0000000000000001"}

    assert exact_net_rank_value(better) > exact_net_rank_value(worse)


def test_train_statistics_reject_invalid_rows_and_hash_payload_stably() -> None:
    from hl_observer.backtesting.train_statistics import number, stable_hash

    assert number("not-a-number") is None
    assert number(float("inf")) is None
    assert stable_hash({"b": 2, "a": 1}) == stable_hash({"a": 1, "b": 2})

    result = summarize_train_rows(
        [
            {"ts": 0, "net": 1.0},
            {"ts": 1, "net": "invalid"},
            {"ts": 1, "net": 2.0},
        ],
        value_key="net",
        timestamp_key="ts",
        trial_count=0,
    )

    assert result["sample_count"] == 1
    assert result["distinct_days"] == 1
    assert result["net_pnl_usd"] == 2.0
    assert result["bonferroni_trial_count"] == 1
    assert result["daily_mean_lcb_usd"] is None
    assert result["total_lcb_usd"] is None


def test_train_statistics_preserves_exact_decimal_net_and_daily_totals() -> None:
    day = 86_400_000
    result = summarize_train_rows(
        [
            {
                "ts": day + 1,
                "net": 0.5,
                "net_exact_decimal": "0.4999999999999996",
            },
            {"ts": day + 2, "net": 4.5, "net_exact_decimal": "4.5"},
        ],
        value_key="net",
        timestamp_key="ts",
        trial_count=1,
    )

    assert result["net_pnl_usd_exact_decimal"] == "4.9999999999999996"
    assert result["net_pnl_usd"] < 5.0
    assert result["daily_net_pnl_usd_exact_decimal"] == ["4.9999999999999996"]
    assert result["daily_net_pnl_usd"][0] < 5.0


def test_empty_or_invalid_train_observations_never_become_zero_pnl() -> None:
    for rows in ([], [{"ts": 86_400_001, "net": True}]):
        result = summarize_train_rows(
            rows,
            value_key="net",
            timestamp_key="ts",
            trial_count=1,
        )

        assert result["sample_count"] == 0
        assert result["net_pnl_usd"] is None
        assert result["net_pnl_usd_exact_decimal"] is None
        assert result["lcb_status"] == "NO_VALID_OBSERVATIONS"
        assert result["profit_factor_status"] == "NO_VALID_OBSERVATIONS"
        assert result["top_positive_trade_share"] is None

    daily = summarize_daily_values([], trial_count=1)
    assert daily["sample_count"] == 0
    assert daily["net_pnl_usd"] is None
    assert daily["net_pnl_usd_exact_decimal"] is None
    assert daily["lcb_status"] == "NO_VALID_OBSERVATIONS"


def test_train_statistics_no_loss_factor_is_strict_json_and_explicit() -> None:
    result = summarize_train_rows(
        [{"ts": 86_400_001, "net": 1.0}],
        value_key="net",
        timestamp_key="ts",
        trial_count=1,
    )

    json.dumps(result, allow_nan=False)
    assert result["profit_factor"] is None
    assert result["profit_factor_status"] == "NO_LOSSES"


def test_calendar_mean_includes_only_explicitly_covered_no_trade_days() -> None:
    day = 86_400_000
    result = summarize_complete_utc_days(
        [
            {"ts": day + 1, "net": 1.0},
            {"ts": day + 2, "net": 2.0},
        ],
        value_key="net",
        timestamp_key="ts",
        complete_day_starts_ms=[day, 2 * day, 3 * day],
    )

    assert result["status"] == "MEASURABLE"
    assert result["calendar_day_net_pnl_usd"] == [3.0, 0.0, 0.0]
    assert result["calendar_day_mean_net_pnl_usd"] == 1.0
    assert result["active_day_mean_net_pnl_usd"] == 3.0
    assert result["zero_trade_days"] == 2


def test_calendar_mean_is_unmeasurable_without_complete_day_coverage() -> None:
    result = summarize_complete_utc_days(
        [{"ts": 86_400_001, "net": 3.0}],
        value_key="net",
        timestamp_key="ts",
        complete_day_starts_ms=None,
    )

    assert result["status"] == "UNMEASURABLE"
    assert result["reason"] == "COMPLETE_UTC_DAY_COVERAGE_MISSING"
    assert result["calendar_day_mean_net_pnl_usd"] is None


def test_calendar_mean_refuses_trade_outside_declared_coverage() -> None:
    day = 86_400_000
    result = summarize_complete_utc_days(
        [{"ts": 2 * day + 1, "net": 1.0}],
        value_key="net",
        timestamp_key="ts",
        complete_day_starts_ms=[day],
    )

    assert result["status"] == "UNMEASURABLE"
    assert result["reason"] == "TRADE_OUTSIDE_COMPLETE_UTC_DAY_COVERAGE"


def test_calendar_mean_rejects_non_utc_day_boundaries_and_duplicates() -> None:
    for coverage in ([1], [86_400_000, 86_400_000]):
        result = summarize_complete_utc_days(
            [],
            value_key="net",
            timestamp_key="ts",
            complete_day_starts_ms=coverage,
        )
        assert result["status"] == "UNMEASURABLE"
        assert result["reason"] == "INVALID_COMPLETE_UTC_DAY_COVERAGE"


def test_calendar_mean_rejects_gaps_in_covered_day_sequence() -> None:
    day = 86_400_000
    result = summarize_complete_utc_days(
        [],
        value_key="net",
        timestamp_key="ts",
        complete_day_starts_ms=[day, 3 * day],
    )

    assert result["status"] == "UNMEASURABLE"
    assert result["reason"] == "NONCONTIGUOUS_COMPLETE_UTC_DAY_COVERAGE"


def test_calendar_active_day_count_uses_trades_not_nonzero_pnl() -> None:
    day = 86_400_000
    result = summarize_complete_utc_days(
        [
            {"ts": day + 1, "net": 1.0},
            {"ts": day + 2, "net": -1.0},
        ],
        value_key="net",
        timestamp_key="ts",
        complete_day_starts_ms=[day, 2 * day],
    )

    assert result["status"] == "MEASURABLE"
    assert result["active_day_count"] == 1
    assert result["zero_trade_days"] == 1
    assert result["active_day_mean_net_pnl_usd"] == 0.0


def test_calendar_pnl_keeps_exact_decimal_below_target_without_rounding_up() -> None:
    day = 86_400_000
    result = summarize_complete_utc_days(
        [
            {"ts": day + 1, "net": 5.0, "net_exact_decimal": "4.999999999999999999"}
        ],
        value_key="net",
        timestamp_key="ts",
        complete_day_starts_ms=[day],
    )

    assert result["status"] == "MEASURABLE"
    assert result["calendar_day_net_pnl_usd_exact_decimal"] == [
        "4.999999999999999999"
    ]
    assert result["calendar_day_net_pnl_usd"][0] < 5.0
    assert result["calendar_total_net_pnl_usd_exact_decimal"] == "4.999999999999999999"


def test_calendar_pnl_rejects_boolean_money_and_fractional_timestamps() -> None:
    day = 86_400_000
    for row in (
        {"ts": day + 1, "net": True},
        {"ts": day + 1.5, "net": 1.0},
    ):
        result = summarize_complete_utc_days(
            [row],
            value_key="net",
            timestamp_key="ts",
            complete_day_starts_ms=[day],
        )
        assert result["status"] == "UNMEASURABLE"
        assert result["reason"] == "INVALID_TRADE_ROW_FOR_CALENDAR_PNL"


def test_lcb_exact_decimal_breaks_float_ties_and_reports_a_conservative_bound() -> None:
    day = 86_400_000
    def summarize(value: str) -> dict:
        return summarize_train_rows(
            [
                {"ts": day * index + 1, "net": float(value), "net_exact_decimal": value}
                for index in range(3)
            ],
            value_key="net",
            timestamp_key="ts",
            trial_count=1,
        )

    worse = summarize("1.00000000000000001")
    better = summarize("1.00000000000000002")

    assert worse["total_lcb_usd"] == better["total_lcb_usd"]
    assert exact_lcb_rank_value(better) > exact_lcb_rank_value(worse)
    assert Decimal(better["total_lcb_numeric_error_bound_usd_exact_decimal"]) > 0
    assert Decimal(better["total_lcb_usd_exact_decimal"]) > 0


def test_lcb_outward_interval_keeps_measured_tiny_positive_value_conservative() -> None:
    day = 86_400_000
    result = summarize_train_rows(
        [
            {"ts": day * index + 1, "net": 1e-80, "net_exact_decimal": "1e-80"}
            for index in range(3)
        ],
        value_key="net",
        timestamp_key="ts",
        trial_count=1,
    )

    lower = Decimal(result["total_lcb_usd_exact_decimal"])
    upper = Decimal(result["total_lcb_upper_bound_usd_exact_decimal"])
    bound = Decimal(result["total_lcb_numeric_error_bound_usd_exact_decimal"])
    assert Decimal(0) < lower <= upper
    assert upper - lower <= bound


def test_lcb_bound_covers_independent_high_precision_decimal_reference() -> None:
    day_ms = 86_400_000
    cases = [
        (["1", "1", "1"], 1),
        (["1e80", "-1e80", "1.0000000000000000000000000000000000001"], 2),
        (["1e-100", "2e-100", "3e-100", "4e-100", "5e-100"], 37),
        (["1e308", "-1e308", "1e308"], 19),
        (["5e-324", "1e-323", "2e-323"], 11),
        ([str(Decimal(index - 32) / Decimal(1000)) for index in range(64)], 10_000),
    ]
    generator = Random(169)
    for case_index in range(24):
        exponent = generator.randint(-120, 120)
        sample_count = 3 + generator.randrange(16)
        exact_values = [
            f"{generator.randint(-9_999, 9_999)}e{exponent}"
            for _ in range(sample_count)
        ]
        cases.append((exact_values, (1, 2, 7, 10_000)[case_index % 4]))

    for exact_values, trial_count in cases:
        rows = [
            {
                "ts": day_ms * (index + 1) + 1,
                "net": float(value),
                "net_exact_decimal": value,
            }
            for index, value in enumerate(exact_values)
        ]
        result = summarize_train_rows(
            rows,
            value_key="net",
            timestamp_key="ts",
            trial_count=trial_count,
        )
        assert result["schema_version"] == "hypersmart.train_selection_statistics.v3"
        assert result["lcb_status"] == "MEASURED"

        with localcontext() as context:
            context.prec = 240
            values = [Decimal(value) for value in exact_values]
            count = Decimal(len(values))
            mean = sum(values, Decimal(0)) / count
            variance = sum(
                ((value - mean) * (value - mean) for value in values),
                Decimal(0),
            ) / Decimal(len(values) - 1)
            standard_error = variance.sqrt() / count.sqrt()
            production_z = Decimal(
                result["critical_z_upper_bound_exact_decimal"]
            )
            reference_quantile = Decimal.from_float(
                -float(ndtri(result["adjusted_one_sided_alpha"]))
            )
            exact_z_total_lcb = (mean - production_z * standard_error) * count
            confidence_lcb = (mean - reference_quantile * standard_error) * count
            reported_total_lcb = Decimal(result["total_lcb_usd_exact_decimal"])
            reported_upper_lcb = Decimal(
                result["total_lcb_upper_bound_usd_exact_decimal"]
            )
            reported_error_bound = Decimal(
                result["total_lcb_numeric_error_bound_usd_exact_decimal"]
            )
            assert production_z >= reference_quantile
            assert _normal_tail_upper_bound(production_z) <= Decimal.from_float(
                result["adjusted_one_sided_alpha"]
            )
            assert reported_total_lcb <= exact_z_total_lcb <= reported_upper_lcb
            assert reported_upper_lcb <= confidence_lcb
            assert reported_upper_lcb - reported_total_lcb <= reported_error_bound
            assert reported_error_bound == Decimal(
                result["total_lcb_arithmetic_error_bound_usd_exact_decimal"]
            )


def test_candidate_selection_refuses_lcb_rank_inside_numeric_error_bound() -> None:
    day = 86_400_000

    def row(candidate: str, value: str) -> dict:
        statistics = summarize_train_rows(
            [
                {
                    "ts": day * index + 1,
                    "net": float(value),
                    "net_exact_decimal": value,
                }
                for index in range(3)
            ],
            value_key="net",
            timestamp_key="ts",
            trial_count=1,
        )
        return {"candidate": candidate, "statistics": statistics}

    close_low = row(
        "low",
        "1." + "0" * 120 + "1",
    )
    close_high = row(
        "high",
        "1." + "0" * 120 + "2",
    )
    assert not lcb_rank_is_numerically_resolved(
        close_high["statistics"], close_low["statistics"]
    )
    selected, status = select_unambiguous_lcb_candidate([close_high, close_low])
    assert selected is None
    assert status == "NUMERIC_LCB_RANK_UNRESOLVED"


def test_candidate_selection_uses_exact_lcb_when_float_values_tie() -> None:
    day = 86_400_000

    def row(candidate: str, value: str) -> dict:
        statistics = summarize_train_rows(
            [
                {
                    "ts": day * index + 1,
                    "net": float(value),
                    "net_exact_decimal": value,
                }
                for index in range(3)
            ],
            value_key="net",
            timestamp_key="ts",
            trial_count=1,
        )
        return {"candidate": candidate, "statistics": statistics}

    lower = row("lower", "1.00000000000000001")
    higher = row("higher", "1.00000000000000002")
    assert lower["statistics"]["total_lcb_usd"] == higher["statistics"]["total_lcb_usd"]
    assert lcb_rank_is_numerically_resolved(
        higher["statistics"], lower["statistics"]
    )
    selected, status = select_unambiguous_lcb_candidate([lower, higher])
    assert selected == higher
    assert status == "NUMERIC_LCB_RANK_RESOLVED"


def test_exact_lcb_keeps_precision_beyond_process_default_decimal_context() -> None:
    day = 86_400_000
    value = "1.000000000000000000000000000000000000000000000000000000000000000001"
    result = summarize_train_rows(
        [
            {"ts": day * index + 1, "net": float(value), "net_exact_decimal": value}
            for index in range(3)
        ],
        value_key="net",
        timestamp_key="ts",
        trial_count=1,
    )

    exact_lcb = Decimal(result["total_lcb_usd_exact_decimal"])
    assert len(exact_lcb.as_tuple().digits) > 28
    assert exact_lcb > 0


def test_equal_lcb_with_nonzero_error_bound_is_not_treated_as_proven_tie() -> None:
    left = {
        "total_lcb_usd_exact_decimal": "1.000000000000000000000000000000000000000000000000000000000000000000000001",
        "total_lcb_numeric_error_bound_usd_exact_decimal": "0.00000000000000000000000000000000000000000000000000000000000000000000001",
    }
    right = {
        **left,
        "total_lcb_numeric_error_bound_usd_exact_decimal": "0.00000000000000000000000000000000000000000000000000000000000000000000002",
    }

    assert not lcb_rank_is_numerically_resolved(left, right)


def test_lcb_rank_rejects_negative_serialized_error_bounds() -> None:
    left = {
        "total_lcb_usd_exact_decimal": "2",
        "total_lcb_numeric_error_bound_usd_exact_decimal": "-100",
    }
    right = {
        "total_lcb_usd_exact_decimal": "1",
        "total_lcb_numeric_error_bound_usd_exact_decimal": "0",
    }

    assert not lcb_rank_is_numerically_resolved(left, right)


def test_daily_lcb_summary_serialization_is_repeatable_and_strict_json() -> None:
    values = ["0.123456789012345678901", "0.223456789012345678901", "0.323456789012345678901"]

    first = summarize_daily_values(values, trial_count=37)
    second = summarize_daily_values(values, trial_count=37)

    first_json = json.dumps(first, sort_keys=True, separators=(",", ":"), allow_nan=False)
    second_json = json.dumps(second, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert first_json == second_json
    assert stable_hash(first) == stable_hash(second)


def test_unrepresentable_daily_pnl_is_not_silently_dropped_from_day_count() -> None:
    day = 86_400_000
    result = summarize_train_rows(
        [
            {"ts": day + 1, "net": 1.5e308},
            {"ts": day + 2, "net": 1.5e308},
            {"ts": 2 * day + 1, "net": 1.0},
            {"ts": 3 * day + 1, "net": 1.0},
        ],
        value_key="net",
        timestamp_key="ts",
        trial_count=1,
    )

    assert result["distinct_days"] == 3
    assert result["daily_net_pnl_usd"] is None
    assert result["lcb_status"] == "NUMERIC_UNREPRESENTABLE"
    assert result["total_lcb_usd_exact_decimal"] is None

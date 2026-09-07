from __future__ import annotations

from hl_observer.backtesting.train_statistics import profit_factor, summarize_train_rows


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
    assert result["daily_mean_lcb_usd"] == 1.0
    assert result["total_lcb_usd"] == 5.0


def test_profit_factor_mixed_pnl_uses_win_loss_ratio() -> None:
    assert profit_factor([3.0, -1.0, 2.0, -1.0]) == 2.5


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

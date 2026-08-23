from __future__ import annotations

from hl_observer.backtesting.train_statistics import summarize_train_rows


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

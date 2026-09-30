from __future__ import annotations

from hl_observer.backtesting.cross_venue_certified import UNION_SOURCE_MODE
from hl_observer.backtesting.cross_venue_v6_coverage_union_train import (
    BONFERRONI_TRIAL_COUNT,
    PREDECLARED_COINS,
    TRAIN_END_MS,
    TRAIN_START_MS,
    coverage_by_coin,
    explore_cross_venue_v6_train,
)


def _row(timestamp: float) -> tuple:
    return (timestamp, "ATOMIC", 99.9, 100.1, 99.9, 100.1)


def test_couverture_v6_ne_lit_que_la_fenetre_train_figee() -> None:
    step = (TRAIN_END_MS - TRAIN_START_MS) / 499
    rows = [_row(TRAIN_START_MS + index * step) for index in range(500)]
    rows.append(_row(TRAIN_END_MS + 1.0))
    coverage = coverage_by_coin({PREDECLARED_COINS[0]: rows})

    assert coverage[PREDECLARED_COINS[0]]["train_rows"] == 500
    assert coverage[PREDECLARED_COINS[0]]["distinct_utc_days"] >= 3
    assert coverage[PREDECLARED_COINS[0]]["coverage_eligible"] is True
    assert coverage[PREDECLARED_COINS[1]]["coverage_eligible"] is False


def test_v6_refuse_de_reduire_univers_ou_multiplicite() -> None:
    result = explore_cross_venue_v6_train(
        {},
        {},
        source_mode=UNION_SOURCE_MODE,
        source_meta={
            "source_mode": UNION_SOURCE_MODE,
            "mapping_verified": True,
            "contract_multipliers_normalized": True,
            "quote_currencies_normalized": True,
            "sizes_normalized_to_usd_notional": True,
        },
    )

    assert result["status"] == "PREDECLARED_CERTIFIED_COVERAGE_REQUIRED"
    assert result["selection_eligible"] is False
    assert result["heldout_evaluated"] is False
    assert BONFERRONI_TRIAL_COUNT == 902
    assert len(result["predeclared_coins"]) == 26
    assert result["real_execution"] is False

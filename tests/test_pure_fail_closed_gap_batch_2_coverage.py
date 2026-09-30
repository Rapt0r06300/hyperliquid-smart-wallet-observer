"""Close three exact pure/fail-closed coverage gaps without runtime I/O."""

from hl_observer.api_governance.reserved_api_quota import QuotaReserve
from hl_observer.arbitrage.leg_sequencing_empirical import ordonner_jambes
from hl_observer.backtesting.risk_sizing import fractional_kelly


def test_three_pure_fail_closed_micro_gaps() -> None:
    quota = QuotaReserve(quota_total=10.0, reserve_critique=5.0)
    assert quota.consommer("DISCOVERY", cout=6.0) is False

    ordered = ordonner_jambes(
        "HL",
        {"proba_echec": 0.01, "latence_ms": 10.0},
        "BINANCE",
        {"proba_echec": 0.02, "latence_ms": 5.0},
    )
    assert ordered["ordre"] == ["BINANCE", "HL"]

    assert fractional_kelly(0.8, 0.0) == 0.0

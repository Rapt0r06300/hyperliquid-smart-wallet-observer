from __future__ import annotations

from hl_observer.ops.pnl_improvement_lab import compare_copy_vault_liquidity_veto
from hl_observer.research.market_quality import assess_copy_vault_market_quality


def _row(*, ts: int, book_ts: int, episode: str, trial: str, spread: float, depth: float, gross: float) -> dict:
    return {
        "opened_at_ms": ts,
        "book_ts_ms": book_ts,
        "episode_id": episode,
        "trial_id": trial,
        "spread_bps": spread,
        "depth_usd": depth,
        "gross_pnl_bps": gross,
        "cost_bps": 2.0,
    }


def test_market_quality_requires_book_snapshot_before_signal() -> None:
    valid = assess_copy_vault_market_quality(
        _row(ts=2_000, book_ts=1_999, episode="e", trial="t", spread=5.0, depth=5_000.0, gross=7.0),
        as_of_ms=2_000,
    )
    assert valid["status"] == "ADMISSIBLE"
    future = assess_copy_vault_market_quality(
        _row(ts=2_000, book_ts=2_001, episode="e", trial="t", spread=5.0, depth=5_000.0, gross=7.0),
        as_of_ms=2_000,
    )
    assert future == {
        "status": "UNMEASURABLE",
        "reason": "NON_CAUSAL_BOOK_EVIDENCE",
        "admissible": False,
    }


def test_liquidity_veto_compares_same_oos_rows_with_full_cost() -> None:
    train = [
        _row(ts=100, book_ts=99, episode="tr-1", trial="a", spread=5.0, depth=5_000.0, gross=7.0),
        _row(ts=110, book_ts=109, episode="tr-2", trial="a", spread=6.0, depth=5_000.0, gross=6.0),
    ]
    oos = [
        _row(ts=2_000, book_ts=1_999, episode="oos-1", trial="b", spread=5.0, depth=5_000.0, gross=7.0),
        _row(ts=2_010, book_ts=2_009, episode="oos-2", trial="b", spread=20.0, depth=100.0, gross=-3.0),
    ]

    result = compare_copy_vault_liquidity_veto(train, oos, cutoff_ms=1_000)

    assert result["status"] == "COMPARABLE"
    assert result["baseline_oos"]["cost_bps"] == 4.0
    assert result["accepted_oos"]["rows"] == 1
    assert result["accepted_oos"]["net_pnl_bps"] == 5.0
    assert result["vetoed_oos"]["rows"] == 1
    assert result["same_oos_episodes_and_cost_fields"] is True
    assert result["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_liquidity_veto_fails_closed_when_every_oos_row_is_rejected() -> None:
    row = _row(ts=2_000, book_ts=1_999, episode="oos-1", trial="b", spread=20.0, depth=100.0, gross=7.0)
    result = compare_copy_vault_liquidity_veto(
        [_row(ts=100, book_ts=99, episode="tr-1", trial="a", spread=5.0, depth=5_000.0, gross=7.0)],
        [row],
        cutoff_ms=1_000,
    )
    assert result["status"] == "UNMEASURABLE"
    assert result["reason"] == "ALL_OOS_ROWS_VETOED"

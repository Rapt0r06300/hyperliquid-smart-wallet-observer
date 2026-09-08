from __future__ import annotations

from hl_observer.backtesting.copy_vault_executable import execute_metaorder


def _metaorder() -> dict:
    return {
        "metaorder_id": "regime-provenance-mo",
        "vault": "0xregime",
        "coin": "BTC",
        "direction": 1,
        "signal_ts_ms": 1_000,
        "first_fill_ts_ms": 1_000,
        "signal_source": "LIVE_WS",
        "causal_forward_eligible": True,
    }


def _book(ts_ms: int, bid: float, ask: float, *, line: int) -> dict:
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "capacity_usd": 1_000.0,
        "source_line": line,
        "causal_observation": True,
    }


def _execute(reference_bid: float, reference_ask: float, *, shifted: bool = False) -> dict:
    if shifted:
        entry_bid, entry_ask, exit_bid, exit_ask = 105.0, 105.04, 106.0, 106.04
    else:
        entry_bid, entry_ask, exit_bid, exit_ask = 100.5, 100.54, 101.0, 101.04
    trade, reason = execute_metaorder(
        _metaorder(),
        [
            _book(1_000, reference_bid, reference_ask, line=1),
            _book(61_000, entry_bid, entry_ask, line=2),
            _book(361_000, exit_bid, exit_ask, line=3),
        ],
        horizon_ms=300_000,
        fee_bps=0.0,
        require_causal_books=True,
    )
    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None
    return trade


def test_copy_vault_regime_is_pre_signal_reference_spread_only() -> None:
    tight_a = _execute(100.00, 100.04)
    tight_b = _execute(100.00, 100.04, shifted=True)
    wide = _execute(99.0, 101.0)

    assert tight_a["regime_id"] == "REF_SPREAD_TIGHT_LE_10BPS"
    assert tight_b["regime_id"] == tight_a["regime_id"]
    assert wide["regime_id"] == "REF_SPREAD_WIDE_GT_10BPS"
    assert tight_a["regime_source"] == "REFERENCE_BOOK_PRE_SIGNAL"
    assert tight_a["regime_reference_ts_ms"] == tight_a["signal_ts_ms"] == 1_000
    assert tight_a["regime_reference_spread_bps"] <= 10.0
    assert wide["regime_reference_spread_bps"] > 10.0

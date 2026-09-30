from __future__ import annotations

from hl_observer.models import DataQuality, SourceMeta
from hl_observer.normalization.fills import fill_dedupe_key, normalize_hyperliquid_fill
from hl_observer.normalization.positions import normalize_hyperliquid_position
from hl_observer.position_lifecycle.reconstructor import (
    LifecycleAction,
    classify_lifecycle_delta,
    event_from_fill,
    reconstruct_lifecycles,
)
from hl_observer.signals.leader_delta import leader_delta_from_lifecycle_event


WALLET = "0x" + "a" * 40


def _meta() -> SourceMeta:
    return SourceMeta(
        source_endpoint="/info:userFillsByTime",
        local_received_ts=1_700_000_001_000,
        raw_hash="raw:test",
        data_quality=DataQuality.OK,
    )


def test_v12_normalizes_hyperliquid_fill_with_dedupe_key():
    result = normalize_hyperliquid_fill(
        {
            "coin": "hype",
            "dir": "Open Long",
            "side": "B",
            "sz": "1.25",
            "px": "42.5",
            "time": 1_700_000_000_000,
            "startPosition": "0",
            "closedPnl": "0",
            "fee": "0.01",
            "oid": "101",
            "tid": "202",
            "hash": "0xf00d",
        },
        wallet=WALLET,
        meta=_meta(),
    )

    assert result.usable
    assert result.fill is not None
    assert result.fill.coin == "HYPE"
    assert result.signed_size_delta == 1.25
    assert result.resulting_position == 1.25
    assert result.dedupe_key == "hash:0xf00d"
    assert fill_dedupe_key(result.fill) == "hash:0xf00d"


def test_v12_normalization_refuses_missing_real_fill_fields():
    result = normalize_hyperliquid_fill({"coin": "BTC", "dir": "Open Long"}, wallet=WALLET, meta=_meta())
    assert result.fill is None
    assert "FILL_SIZE_INVALID" in result.warnings
    assert "FILL_PRICE_INVALID" in result.warnings
    assert "FILL_TIME_MISSING" in result.warnings


def test_v12_normalizes_clearinghouse_position_shape():
    result = normalize_hyperliquid_position(
        {
            "position": {
                "coin": "eth",
                "szi": "-2.5",
                "entryPx": "3500",
                "unrealizedPnl": "-12.4",
            }
        },
        wallet=WALLET,
        meta=_meta(),
    )

    assert result.usable
    assert result.position is not None
    assert result.position.coin == "ETH"
    assert result.position.signed_size == -2.5
    assert result.position.entry_px == 3500


def test_v12_lifecycle_classifies_open_add_reduce_close_and_flip():
    assert classify_lifecycle_delta(0, 1) == LifecycleAction.OPEN_LONG
    assert classify_lifecycle_delta(0, -1) == LifecycleAction.OPEN_SHORT
    assert classify_lifecycle_delta(1, 2) == LifecycleAction.INCREASE
    assert classify_lifecycle_delta(-1, -2) == LifecycleAction.INCREASE
    assert classify_lifecycle_delta(2, 1) == LifecycleAction.REDUCE
    assert classify_lifecycle_delta(-2, -1) == LifecycleAction.REDUCE
    assert classify_lifecycle_delta(1, 0) == LifecycleAction.CLOSE_LONG
    assert classify_lifecycle_delta(-1, 0) == LifecycleAction.CLOSE_SHORT
    assert classify_lifecycle_delta(1, -1) == LifecycleAction.FLIP
    assert classify_lifecycle_delta(-1, 1) == LifecycleAction.FLIP
    assert classify_lifecycle_delta(1, 0, liquidation=True) == LifecycleAction.LIQUIDATION


def test_v12_event_from_fill_and_lifecycle_reconstruction():
    open_result = normalize_hyperliquid_fill(
        {
            "coin": "HYPE",
            "dir": "Open Long",
            "side": "B",
            "sz": "2",
            "px": "40",
            "time": 1_700_000_000_000,
            "startPosition": "0",
            "tid": "1",
        },
        wallet=WALLET,
        meta=_meta(),
    )
    close_result = normalize_hyperliquid_fill(
        {
            "coin": "HYPE",
            "dir": "Close Long",
            "side": "A",
            "sz": "2",
            "px": "41",
            "time": 1_700_000_010_000,
            "startPosition": "2",
            "closedPnl": "2",
            "tid": "2",
        },
        wallet=WALLET,
        meta=_meta(),
    )

    fills = [open_result.fill, close_result.fill]
    assert all(fill is not None for fill in fills)
    episodes = reconstruct_lifecycles(WALLET, [fill for fill in fills if fill is not None])

    assert len(episodes) == 1
    assert episodes[0].status == "CLOSED"
    assert [event.action for event in episodes[0].events] == [
        LifecycleAction.OPEN_LONG,
        LifecycleAction.CLOSE_LONG,
    ]
    assert episodes[0].events[-1].closed_pnl == 2


def test_v12_flip_and_liquidation_never_become_safe_entry_deltas():
    flip_fill = normalize_hyperliquid_fill(
        {
            "coin": "HYPE",
            "dir": "Open Short",
            "side": "A",
            "sz": "3",
            "px": "39",
            "time": 1_700_000_020_000,
            "startPosition": "1",
            "tid": "flip",
        },
        wallet=WALLET,
        meta=_meta(),
    ).fill
    assert flip_fill is not None
    flip_event = event_from_fill(flip_fill)
    flip_delta = leader_delta_from_lifecycle_event(flip_event, observed_at_ms=1_700_000_020_200)

    assert flip_event.action == LifecycleAction.FLIP
    assert not flip_delta.safe_for_paper_candidate
    assert "FLIP_NO_DIRECT_PAPER_ENTRY" in flip_delta.reason_codes

    liquidation_event = type(flip_event)(
        wallet=flip_event.wallet,
        coin=flip_event.coin,
        action=LifecycleAction.LIQUIDATION,
        previous_size=1.0,
        current_size=0.0,
        size_delta=-1.0,
        time_ms=flip_event.time_ms,
        price=flip_event.price,
        confidence=0.0,
        evidence_ref="liq",
    )
    liq_delta = leader_delta_from_lifecycle_event(liquidation_event, observed_at_ms=1_700_000_020_300)
    assert not liq_delta.safe_for_paper_candidate
    assert "LIQUIDATION_NO_DIRECT_PAPER_ENTRY" in liq_delta.reason_codes


def test_v12_entry_leader_delta_is_deterministic_and_evidenced():
    fill = normalize_hyperliquid_fill(
        {
            "coin": "BTC",
            "dir": "Open Short",
            "side": "A",
            "sz": "0.1",
            "px": "100000",
            "time": 1_700_000_000_000,
            "startPosition": "0",
            "tid": "abc",
        },
        wallet=WALLET,
        meta=_meta(),
    ).fill
    assert fill is not None
    event = event_from_fill(fill)
    d1 = leader_delta_from_lifecycle_event(event, observed_at_ms=1_700_000_000_250)
    d2 = leader_delta_from_lifecycle_event(event, observed_at_ms=1_700_000_000_250)

    assert d1.delta_id == d2.delta_id
    assert d1.action == LifecycleAction.OPEN_SHORT
    assert d1.is_entry
    assert d1.safe_for_paper_candidate
    assert d1.evidence_ref == "abc"

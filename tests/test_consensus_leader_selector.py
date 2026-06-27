from hl_observer.copying.consensus_leader_selector import select_consensus_leaders_from_deltas
from hl_observer.storage.models import PositionDeltaModel, TopWallet


def _leader(wallet: str, score: float) -> TopWallet:
    return TopWallet(
        wallet_address=wallet,
        rank=1,
        source="test",
        score=score,
        selected_at_ms=1_000,
        status="selected",
    )


def _delta(
    wallet: str,
    *,
    coin: str = "ETH",
    delta_type: str = "open_long",
    ms: int = 1_000,
    notional: float = 25_000.0,
) -> PositionDeltaModel:
    is_short = "short" in delta_type
    return PositionDeltaModel(
        wallet_address=wallet,
        coin=coin,
        previous_side=None,
        new_side="short" if is_short else "long",
        previous_size=0.0,
        current_size=-1.0 if is_short else 1.0,
        new_size=-1.0 if is_short else 1.0,
        delta_size=1.0,
        delta_notional_usdc=notional,
        action=delta_type.upper(),
        exchange_ts=ms,
        side="short" if is_short else "long",
        price=2_500.0,
        fill_size=1.0,
        delta_type=delta_type,
        confidence_score=0.95,
        detected_at_ms=ms,
        delta_hash=f"{wallet}:{coin}:{delta_type}:{ms}",
    )


def test_consensus_leader_selector_prioritizes_same_coin_same_direction_cluster():
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    wallet_c = "0x" + "c" * 40
    report = select_consensus_leaders_from_deltas(
        [
            _delta(wallet_a, coin="ETH", delta_type="open_long", ms=10_000),
            _delta(wallet_b, coin="ETH", delta_type="add_long", ms=12_500),
            _delta(wallet_c, coin="BTC", delta_type="open_short", ms=12_700),
        ],
        [_leader(wallet_a, 98), _leader(wallet_b, 92), _leader(wallet_c, 99)],
        now_timestamp_ms=13_000,
        max_leaders=2,
        active_window_ms=60_000,
        consensus_window_ms=4_000,
        min_wallets=2,
    )

    assert report.groups_seen == 1
    assert report.groups[0].coin == "ETH"
    assert report.groups[0].direction == "LONG"
    assert report.groups[0].wallet_count == 2
    assert report.selected_wallets == [wallet_a, wallet_b]


def test_consensus_leader_selector_refuses_stale_or_single_wallet_clusters():
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    report = select_consensus_leaders_from_deltas(
        [
            _delta(wallet_a, coin="ETH", delta_type="open_long", ms=1_000),
            _delta(wallet_b, coin="ETH", delta_type="reduce_long", ms=59_000),
        ],
        [_leader(wallet_a, 98), _leader(wallet_b, 92)],
        now_timestamp_ms=70_000,
        max_leaders=2,
        active_window_ms=10_000,
        consensus_window_ms=4_000,
        min_wallets=2,
    )

    assert report.selected_wallets == []
    assert report.groups_seen == 0
    assert report.rejected_reasons["stale_outside_active_window"] == 2

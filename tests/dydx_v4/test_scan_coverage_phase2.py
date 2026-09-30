from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
from hyper_smart_observer.dydx_v4.config import DydxNetwork, DydxV4Config
from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver
from hyper_smart_observer.dydx_v4.wallet_discovery import WalletScore


def _wallet(n: int) -> WalletScore:
    return WalletScore(
        address=f"dydx1{'a' * 38}{n}",
        subaccount_number=0,
        usdc_balance=10_000.0,
        total_score=100.0 - n,
    )


def _observer(config: DydxV4Config, shortlist: list[WalletScore]) -> DydxLiveObserver:
    rest = MagicMock()
    rest.get_positions.return_value = {"positions": []}
    return DydxLiveObserver(
        config=config,
        rest_client=rest,
        cluster_detector=DydxClusterDetector(consensus_window_ms=60_000, min_notional_usdc=0.0),
        initial_shortlist=shortlist,
        poll_interval_s=0.01,
    )


def test_rest_poll_cap_is_respected() -> None:
    cfg = DydxV4Config(
        network=DydxNetwork.TESTNET,
        market_flow_enabled=False,
        rest_poll_cap=2,
    )
    obs = _observer(cfg, [_wallet(i) for i in range(5)])
    seen: list[str] = []
    obs._poll_one_wallet = lambda w: seen.append(w.address)

    obs._poll_shortlist_live()

    assert seen == [obs._shortlist[0].address, obs._shortlist[1].address]


def test_merge_harvester_dedupes_and_respects_max_decision_wallets() -> None:
    cfg = DydxV4Config(
        network=DydxNetwork.TESTNET,
        market_flow_enabled=False,
        max_decision_wallets=3,
    )
    existing = WalletScore(address="dydx1" + "a" * 39, total_score=90.0)
    obs = _observer(cfg, [existing])
    top = [
        (existing.address, 99.0),
        ("dydx1" + "b" * 39, 80.0),
        ("dydx1" + "c" * 39, 70.0),
        ("dydx1" + "d" * 39, 60.0),
    ]
    obs.fast_scan = SimpleNamespace(
        harvester=SimpleNamespace(top_for_scanner=lambda n=None: top[:n])
    )

    obs._merge_harvester_into_shortlist()

    addresses = [w.address for w in obs._shortlist]
    assert addresses == [existing.address, "dydx1" + "b" * 39, "dydx1" + "c" * 39]
    assert len(addresses) == len(set(addresses)) == 3


def test_get_status_exposes_scan_coverage_counters() -> None:
    cfg = DydxV4Config(
        network=DydxNetwork.TESTNET,
        market_flow_enabled=False,
        rest_poll_cap=7,
    )
    obs = _observer(cfg, [_wallet(i) for i in range(5)])
    obs.fast_scan = SimpleNamespace(stats=lambda: {"hot_wallets": 4})
    obs._flow_monitor = SimpleNamespace(stats={"trades_seen": 123, "signals": 2})
    obs._stream_stats["fills_seen"] = 9

    status = obs.get_status()

    assert status["scan"]["discovery_wallets"] == 5
    assert status["scan"]["ws_tracked"] == 4
    assert status["scan"]["rest_polled"] == 5
    assert status["scan"]["rest_poll_cap"] == 7
    assert status["scan"]["flow_trades_seen"] == 123
    assert status["scan"]["flow_signals"] == 2
    assert status["scan"]["stream_fills_seen"] == 9

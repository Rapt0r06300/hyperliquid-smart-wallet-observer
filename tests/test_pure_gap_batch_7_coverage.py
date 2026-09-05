from __future__ import annotations

from hl_observer.accounting.fixed_point_core import UNMEASURABLE, vers_unites
from hl_observer.clusters.wallet_clusterer import cluster_wallets_by_coin


def test_fixed_point_rejects_decimal_parse_failure() -> None:
    assert vers_unites("not-a-decimal", scale=2) == UNMEASURABLE


def test_wallet_clusterer_groups_sorted_coins_and_unknown_wallets() -> None:
    assert cluster_wallets_by_coin(
        {"alice": {"ETH", "BTC"}, "bob": set(), "carol": {"BTC", "ETH"}}
    ) == {"BTC,ETH": ["alice", "carol"], "unknown": ["bob"]}

from hl_observer.universe.dynamic_whitelist import build_dynamic_whitelist
from hl_observer.universe.blacklist import filter_blacklisted


def test_dynamic_whitelist_and_blacklist():
    whitelist = build_dynamic_whitelist(
        [
            {"coin": "HYPE", "volume_usdt": 1_000_000, "depth_usdt": 50_000},
            {"coin": "ILLQ", "volume_usdt": 10, "depth_usdt": 5},
        ]
    )
    assert whitelist == ("HYPE",)
    assert filter_blacklisted(whitelist, ["HYPE"]) == ()

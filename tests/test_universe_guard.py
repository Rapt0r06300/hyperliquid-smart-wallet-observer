"""S2 — univers & delistings."""
from __future__ import annotations

from hl_observer.market.universe_guard import diff_univers, coin_tradeable


def test_diff():
    d = diff_univers(["HYPE", "PURR"], ["HYPE", "AZTEC"])
    assert d["ajoutes"] == ["AZTEC"] and d["retires"] == ["PURR"]


def test_tradeable_deny_by_default():
    assert coin_tradeable("HYPE", ["HYPE", "PURR"]) is True
    assert coin_tradeable("XXX", ["HYPE"]) is False        # hors univers -> non tradeable

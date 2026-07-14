"""Tests outils d'intégrité."""
from __future__ import annotations

from hl_observer.backtesting.integrity_tools import golden_file_check, seeded_rng, spoofing_flags


def test_seeded_rng_reproducible():
    a = [seeded_rng(7).random() for _ in range(3)]
    b = [seeded_rng(7).random() for _ in range(3)]
    assert a == b


def test_golden_file_check():
    assert golden_file_check({"a": 1, "b": 2}, {"b": 2, "a": 1}) is True
    assert golden_file_check({"a": 1}, {"a": 2}) is False


def test_spoofing_detects_fast_cancel_of_large_order():
    events = [
        ("o1", "add", 1000.0, 0.0),
        ("o1", "cancel", 1000.0, 0.3),    # gros ordre annulé vite -> spoof
        ("o2", "add", 5.0, 1.0),
        ("o2", "cancel", 5.0, 1.1),       # petit -> pas flag
    ]
    assert spoofing_flags(events, large_size=100.0, max_lifetime=1.0) == ["o1"]

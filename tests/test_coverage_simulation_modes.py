from __future__ import annotations

import pytest

from hl_observer.simulation.modes import (
    MAX_HARD_SIGNAL_AGE_MS,
    MAX_LIVE_SIGNAL_AGE_MS,
    SignalSource,
    SimulationMode,
    TEST_FIXTURE_WALLET_ADDRESSES,
    is_test_fixture_wallet,
)


@pytest.mark.parametrize(
    ("mode", "live", "backtest", "replay", "fixture"),
    [
        (SimulationMode.LIVE, True, False, False, False),
        ("live", True, False, False, False),
        (SimulationMode.BACKTEST, False, True, False, False),
        ("backtest", False, True, False, False),
        (SimulationMode.REPLAY, False, False, True, False),
        ("replay", False, False, True, False),
        (SimulationMode.TEST_FIXTURE, False, False, False, True),
        ("test_fixture", False, False, False, True),
        (None, False, False, False, False),
    ],
)
def test_simulation_mode_predicates(mode, live, backtest, replay, fixture) -> None:
    assert SimulationMode.is_live(mode) is live
    assert SimulationMode.is_backtest(mode) is backtest
    assert SimulationMode.is_replay(mode) is replay
    assert SimulationMode.is_test_fixture(mode) is fixture


@pytest.mark.parametrize(
    ("source", "live_eligible", "replay"),
    [
        (SignalSource.FRESH, True, False),
        ("fresh", True, False),
        (SignalSource.REPLAY_JSONL, False, True),
        ("replay_jsonl", False, True),
        (SignalSource.BACKTEST_DB, False, True),
        ("backtest_db", False, True),
        (SignalSource.TEST, False, False),
        (None, False, False),
    ],
)
def test_signal_source_predicates(source, live_eligible, replay) -> None:
    assert SignalSource.is_live_eligible(source) is live_eligible
    assert SignalSource.is_replay(source) is replay


def test_fixture_wallet_detection_is_case_insensitive_and_fail_closed() -> None:
    fixture = next(iter(TEST_FIXTURE_WALLET_ADDRESSES))
    assert is_test_fixture_wallet(fixture)
    assert is_test_fixture_wallet(fixture.upper())
    assert is_test_fixture_wallet(None) is False
    assert is_test_fixture_wallet("") is False
    assert is_test_fixture_wallet("0x1234567890123456789012345678901234567890") is False


def test_signal_age_constants_preserve_strict_live_separation() -> None:
    assert MAX_LIVE_SIGNAL_AGE_MS == 4_000
    assert MAX_HARD_SIGNAL_AGE_MS == 8_000
    assert MAX_LIVE_SIGNAL_AGE_MS < MAX_HARD_SIGNAL_AGE_MS

"""Simulation modes and signal sources for strict separation of live vs replay."""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass
class SimulationMode(StrEnum):
    """
    Simulation modes for separating concerns and PnL reporting.

    - LIVE: Real signals, fresh (< 4s), real wallets → PnL LIVE only
    - BACKTEST: Replay from DB/logs, all signals → PnL BACKTEST only
    - REPLAY: Local jsonl replay, debug/research → separate reporting
    - TEST_FIXTURE: Fixture wallets (0x111...), never in PnL LIVE
    """

    LIVE = "live"
    BACKTEST = "backtest"
    REPLAY = "replay"
    TEST_FIXTURE = "test_fixture"

    @classmethod
    def is_live(cls, mode: SimulationMode | str | None) -> bool:
        """Check if mode is LIVE."""
        return str(mode).lower() == cls.LIVE.value

    @classmethod
    def is_backtest(cls, mode: SimulationMode | str | None) -> bool:
        """Check if mode is BACKTEST."""
        return str(mode).lower() == cls.BACKTEST.value

    @classmethod
    def is_replay(cls, mode: SimulationMode | str | None) -> bool:
        """Check if mode is REPLAY."""
        return str(mode).lower() == cls.REPLAY.value

    @classmethod
    def is_test_fixture(cls, mode: SimulationMode | str | None) -> bool:
        """Check if mode is TEST_FIXTURE."""
        return str(mode).lower() == cls.TEST_FIXTURE.value


class SignalSource(StrEnum):
    """
    Source of signal data for provenance tracking.

    - FRESH: Live WebSocket or REST (< 4s old)
    - REPLAY_JSONL: Local jsonl log replay
    - BACKTEST_DB: From database (historical)
    - TEST: Test fixtures
    """

    FRESH = "fresh"
    REPLAY_JSONL = "replay_jsonl"
    BACKTEST_DB = "backtest_db"
    TEST = "test"

    @classmethod
    def is_live_eligible(cls, source: SignalSource | str | None) -> bool:
        """Check if source is eligible for LIVE PnL."""
        return str(source).lower() == cls.FRESH.value

    @classmethod
    def is_replay(cls, source: SignalSource | str | None) -> bool:
        """Check if source is replay-type."""
        src_str = str(source).lower()
        return src_str in {cls.REPLAY_JSONL.value, cls.BACKTEST_DB.value}


# Fixture wallet addresses that must NEVER appear in LIVE PnL
TEST_FIXTURE_WALLET_ADDRESSES = {
    "0x1111111111111111111111111111111111111111",
    "0x2222222222222222222222222222222222222222",
    "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "0x0000000000000000000000000000000000000000",
}


def is_test_fixture_wallet(wallet_address: str | None) -> bool:
    """Check if wallet is a test fixture address."""
    if not wallet_address:
        return False
    normalized = str(wallet_address or "").lower()
    return normalized in TEST_FIXTURE_WALLET_ADDRESSES


# Live signal freshness constraints
MAX_LIVE_SIGNAL_AGE_MS = 4_000  # 4 seconds for live signals
MAX_HARD_SIGNAL_AGE_MS = 8_000  # 8 seconds absolute max before backtest only

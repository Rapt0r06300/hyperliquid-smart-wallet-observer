"""Signal freshness and validity guards for live trading eligibility."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from hl_observer.simulation.modes import (
    MAX_HARD_SIGNAL_AGE_MS,
    MAX_LIVE_SIGNAL_AGE_MS,
    SignalSource,
    SimulationMode,
    is_test_fixture_wallet,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FreshnessGate:
    """Result of signal freshness evaluation."""

    passed: bool
    reason: str
    signal_age_ms: int | None = None
    mode_eligible: SimulationMode | None = None


def evaluate_signal_freshness(
    signal_age_ms: int,
    leader_wallet: str | None,
    current_mode: SimulationMode,
) -> FreshnessGate:
    """
    Evaluate if signal is fresh enough for LIVE mode.

    Rules:
    - LIVE mode: signal_age_ms < MAX_LIVE_SIGNAL_AGE_MS (4s)
    - BACKTEST mode: signal_age_ms < MAX_HARD_SIGNAL_AGE_MS (8s)
    - TEST_FIXTURE: always blocked from LIVE
    - Too old: demote to BACKTEST

    Returns:
        FreshnessGate with pass/fail and eligible mode
    """
    # Test fixture wallets never eligible for LIVE
    if is_test_fixture_wallet(leader_wallet):
        return FreshnessGate(
            passed=False,
            reason="TEST_FIXTURE_WALLET_EXCLUDED_FROM_LIVE",
            signal_age_ms=signal_age_ms,
            mode_eligible=SimulationMode.TEST_FIXTURE,
        )

    # Check age against mode
    if current_mode == SimulationMode.LIVE:
        if signal_age_ms <= MAX_LIVE_SIGNAL_AGE_MS:
            return FreshnessGate(
                passed=True,
                reason="SIGNAL_FRESH_FOR_LIVE",
                signal_age_ms=signal_age_ms,
                mode_eligible=SimulationMode.LIVE,
            )
        elif signal_age_ms <= MAX_HARD_SIGNAL_AGE_MS:
            return FreshnessGate(
                passed=False,
                reason=f"SIGNAL_AGE_{signal_age_ms}MS_EXCEEDS_LIVE_{MAX_LIVE_SIGNAL_AGE_MS}MS_DEMOTE_TO_BACKTEST",
                signal_age_ms=signal_age_ms,
                mode_eligible=SimulationMode.BACKTEST,
            )
        else:
            return FreshnessGate(
                passed=False,
                reason=f"SIGNAL_AGE_{signal_age_ms}MS_EXCEEDS_HARD_LIMIT_{MAX_HARD_SIGNAL_AGE_MS}MS_REJECT",
                signal_age_ms=signal_age_ms,
                mode_eligible=None,
            )

    # BACKTEST mode: allow up to hard limit
    if current_mode == SimulationMode.BACKTEST:
        if signal_age_ms <= MAX_HARD_SIGNAL_AGE_MS:
            return FreshnessGate(
                passed=True,
                reason="SIGNAL_ACCEPTABLE_FOR_BACKTEST",
                signal_age_ms=signal_age_ms,
                mode_eligible=SimulationMode.BACKTEST,
            )
        else:
            return FreshnessGate(
                passed=False,
                reason=f"SIGNAL_AGE_{signal_age_ms}MS_EXCEEDS_BACKTEST_HARD_LIMIT",
                signal_age_ms=signal_age_ms,
                mode_eligible=None,
            )

    # REPLAY and TEST_FIXTURE: accept all ages for analysis
    return FreshnessGate(
        passed=True,
        reason=f"SIGNAL_ACCEPTED_IN_{current_mode.upper()}_MODE",
        signal_age_ms=signal_age_ms,
        mode_eligible=current_mode,
    )


def validate_signal_for_live(
    signal_age_ms: int,
    leader_wallet: str | None,
    signal_source: SignalSource,
) -> tuple[bool, str]:
    """
    Strict validation for LIVE PnL eligibility.

    Returns:
        (is_eligible, reason_or_empty)
    """
    # Must be from FRESH source
    if not SignalSource.is_live_eligible(signal_source):
        return False, f"SIGNAL_SOURCE_{signal_source.value}_NOT_ELIGIBLE_FOR_LIVE"

    # Must be fresh
    if signal_age_ms > MAX_LIVE_SIGNAL_AGE_MS:
        return False, f"SIGNAL_AGE_{signal_age_ms}MS_EXCEEDS_LIVE_MAX_{MAX_LIVE_SIGNAL_AGE_MS}MS"

    # Must not be test fixture
    if is_test_fixture_wallet(leader_wallet):
        return False, "TEST_FIXTURE_WALLET"

    return True, ""


def categorize_signal_by_freshness(signal_age_ms: int) -> str:
    """Categorize signal by age bucket."""
    if signal_age_ms <= 1_000:
        return "ULTRA_FRESH"
    elif signal_age_ms <= MAX_LIVE_SIGNAL_AGE_MS:
        return "FRESH"
    elif signal_age_ms <= 10_000:
        return "WARM"
    elif signal_age_ms <= 30_000:
        return "STALE"
    else:
        return "VERY_STALE"

"""V15 #188 — Multi-confirmation guard: require >=1 of RVOL / impulse / absorption / OBI / OBI-delta.

Prevents entering on a bare bias with no microstructure backing. Pure: counts how many
independent confirmations fire and reports whether the minimum is met. Promotion-ready.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"
REJECT_REASON = "REJECT_NO_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    confirmations: tuple[str, ...]
    count: int
    ok: bool


def multi_confirmation(
    *,
    rvol_spike: bool = False,
    impulse: bool = False,
    absorption: bool = False,
    obi_confirms: bool = False,
    obi_delta_confirms: bool = False,
    min_confirmations: int = 1,
) -> ConfirmationResult:
    fired = [
        name for name, on in (
            ("RVOL", rvol_spike), ("IMPULSE", impulse), ("ABSORPTION", absorption),
            ("OBI", obi_confirms), ("OBI_DELTA", obi_delta_confirms),
        ) if on
    ]
    return ConfirmationResult(tuple(fired), len(fired), len(fired) >= max(1, int(min_confirmations)))


def apply_confirmation_promotion(
    *, score_reason: str, confirmed: bool | None, authoritative: bool, accept_marker: str = ACCEPT_MARKER,
) -> str:
    if authoritative and score_reason == accept_marker and confirmed is False:
        return REJECT_REASON
    return score_reason


__all__ = ["ACCEPT_MARKER", "REJECT_REASON", "ConfirmationResult", "multi_confirmation", "apply_confirmation_promotion"]

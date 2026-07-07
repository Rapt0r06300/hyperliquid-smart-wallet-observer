"""Lifecycle -> NO_TRADE mapping (V12 - compose D PositionLifecycle + taxonomie §17).

Pure helper: given a classified lifecycle action, return the canonical NO_TRADE code
that should block a copy entry (or None if the lifecycle itself does not block).
Deny-by-default elsewhere; this only encodes the lifecycle-specific reasons. No I/O,
no order, no fabrication.
"""

from __future__ import annotations

from hl_observer.signals.no_trade_taxonomy import resolve
from hl_observer.wallets.position_delta_engine import PositionAction


def lifecycle_no_trade_code(action, *, has_known_position: bool = True) -> str | None:
    a = action if isinstance(action, PositionAction) else PositionAction(str(action).upper())
    if a == PositionAction.UNKNOWN:
        code = "LIFECYCLE_UNKNOWN"
    elif a == PositionAction.FLIP:
        code = "AMBIGUOUS_FLIP"
    elif a in {PositionAction.CLOSE, PositionAction.REDUCE} and not has_known_position:
        code = "ORPHAN_CLOSE"
    else:
        return None
    return resolve(code).value


__all__ = ["lifecycle_no_trade_code"]

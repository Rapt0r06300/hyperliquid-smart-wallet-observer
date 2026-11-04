from __future__ import annotations

import math


def simulated_rejection(api_unstable: bool, min_notional_ok: bool = True) -> bool:
    return api_unstable or not min_notional_ok


def stale_order_cancellation_receipt(*, age_ms: object, max_age_ms: object, state: object) -> dict[str, object]:
    """Cancel a paper order only when age and state are observed and valid."""

    try:
        age, maximum = int(age_ms), int(max_age_ms)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "cancel": False, "reason": "AGE_INVALID"}
    if isinstance(age_ms, bool) or isinstance(max_age_ms, bool) or age < 0 or maximum < 0 or not isinstance(state, str) or not state.strip():
        return {"status": "UNMEASURABLE", "cancel": False, "reason": "ORDER_STATE_INVALID"}
    cancel = age > maximum and state.upper() not in {"CLOSED", "FILLED"}
    return {"status": "PROVEN", "cancel": cancel, "reason": "STALE_ORDER" if cancel else "ORDER_FRESH_OR_TERMINAL"}

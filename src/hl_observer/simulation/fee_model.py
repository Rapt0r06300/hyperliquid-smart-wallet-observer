from __future__ import annotations

import math


def compute_fee_usdc(notional_usdc: float, fee_bps: float) -> float:
    if isinstance(notional_usdc, bool) or isinstance(fee_bps, bool):
        raise ValueError("fee inputs must be numeric")
    try:
        notional = float(notional_usdc)
        fee = float(fee_bps)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("fee inputs must be numeric") from exc
    if not math.isfinite(notional) or not math.isfinite(fee) or notional < 0.0 or fee < 0.0:
        raise ValueError("fee inputs must be finite and non-negative")
    return round(notional * fee / 10_000.0, 10)


def fee_tier_validity_receipt(
    *,
    fee_bps: object,
    valid_from_epoch_ms: object,
    valid_until_epoch_ms: object | None,
    as_of_epoch_ms: object,
    source: object,
) -> dict[str, object]:
    """Validate a fee tier at the observation timestamp without untrusted refreshes."""
    values = (fee_bps, valid_from_epoch_ms, as_of_epoch_ms)
    if any(isinstance(value, bool) for value in values):
        return {"status": "UNMEASURABLE", "valid": False, "reason": "FEE_TIER_INPUT_INVALID"}
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
        return {"status": "UNMEASURABLE", "reason": "FEE_TIER_OBSERVATION_INVALID"}
    if valid_until_epoch_ms is not None and (
        isinstance(valid_until_epoch_ms, bool)
        or not isinstance(valid_until_epoch_ms, (int, float))
        or not math.isfinite(float(valid_until_epoch_ms))
    ):
        return {"status": "UNMEASURABLE", "reason": "FEE_TIER_EXPIRY_INVALID"}
    if not isinstance(source, str) or not source.strip() or float(fee_bps) < 0.0:
        return {"status": "UNMEASURABLE", "reason": "FEE_TIER_SOURCE_OR_VALUE_INVALID"}
    start = float(valid_from_epoch_ms)
    as_of = float(as_of_epoch_ms)
    end = None if valid_until_epoch_ms is None else float(valid_until_epoch_ms)
    if end is not None and end <= start:
        return {"status": "UNMEASURABLE", "reason": "FEE_TIER_INTERVAL_INVALID"}
    valid = as_of >= start and (end is None or as_of < end)
    return {"status": "PROVEN" if valid else "UNMEASURABLE", "valid": valid, "fee_bps": round(float(fee_bps), 10), "source": source.strip(), "as_of_epoch_ms": as_of, "reason": "VALID_AT_OBSERVATION" if valid else "FEE_TIER_NOT_VALID_AT_OBSERVATION"}


__all__ = ["compute_fee_usdc", "fee_tier_validity_receipt"]

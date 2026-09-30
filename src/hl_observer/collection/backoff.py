from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    base_seconds: float = 0.25
    max_seconds: float = 30.0
    jitter_ratio: float = 0.10


@dataclass(frozen=True, slots=True)
class BackoffDecision:
    delay_seconds: float
    reason: str
    retry_after_respected: bool = False


def compute_backoff_delay(
    *,
    attempt: int,
    policy: BackoffPolicy | None = None,
    retry_after_seconds: float | None = None,
    status_code: int | None = None,
    shard_key: str = "",
) -> BackoffDecision:
    """Compute a bounded deterministic backoff delay.

    This is collection resilience only. It does not bypass limits; it slows down
    when the upstream tells us to slow down.
    """

    policy = policy or BackoffPolicy()
    if retry_after_seconds is not None and retry_after_seconds >= 0:
        return BackoffDecision(
            delay_seconds=min(float(retry_after_seconds), policy.max_seconds),
            reason="RETRY_AFTER",
            retry_after_respected=True,
        )
    attempt = max(0, int(attempt))
    raw_delay = policy.base_seconds * (2 ** attempt)
    jitter = _stable_jitter(shard_key or str(status_code or "generic"), policy.jitter_ratio)
    delay = min(policy.max_seconds, raw_delay * (1.0 + jitter))
    if status_code in {429, 403}:
        reason = "RATE_LIMIT_OR_FORBIDDEN_BACKOFF"
    elif status_code is not None and status_code >= 500:
        reason = "SERVER_ERROR_BACKOFF"
    else:
        reason = "GENERIC_BACKOFF"
    return BackoffDecision(delay_seconds=delay, reason=reason)


def _stable_jitter(value: str, ratio: float) -> float:
    ratio = min(max(float(ratio), 0.0), 1.0)
    if ratio == 0:
        return 0.0
    total = sum(ord(ch) for ch in value)
    bucket = (total % 201) - 100
    return (bucket / 100.0) * ratio

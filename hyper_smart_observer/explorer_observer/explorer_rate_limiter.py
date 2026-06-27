from __future__ import annotations

from hyper_smart_observer.hyperliquid_client.rate_limiter import LocalRateLimiter


class ExplorerRateLimiter(LocalRateLimiter):
    """Strict read-only explorer limiter. Defaults should remain conservative."""

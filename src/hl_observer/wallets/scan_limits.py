from __future__ import annotations


def clamp_scan_limit(requested: int, configured_max: int) -> int:
    return max(0, min(requested, configured_max))

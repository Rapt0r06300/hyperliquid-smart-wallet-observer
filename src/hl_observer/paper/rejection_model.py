from __future__ import annotations


def simulated_rejection(api_unstable: bool, min_notional_ok: bool = True) -> bool:
    return api_unstable or not min_notional_ok

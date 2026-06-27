from __future__ import annotations


def reconcile_follow_signal(*, expected_coin: str, observed_coin: str) -> tuple[bool, str]:
    ok = expected_coin.upper() == observed_coin.upper()
    return ok, "ok" if ok else "coin_mismatch"

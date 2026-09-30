from __future__ import annotations

from hl_observer.wallets.leaderboard_validation import (
    is_full_wallet_address,
    is_truncated_wallet_display,
)


def validate_explorer_wallet_address(value: str | None) -> tuple[bool, str]:
    if not value:
        return False, "EVENT_WITHOUT_ADDRESS"
    if is_truncated_wallet_display(value) or "..." in value:
        return False, "TRUNCATED_ADDRESS_REJECTED"
    if not is_full_wallet_address(value):
        return False, "INVALID_ADDRESS_REJECTED"
    return True, "FULL_ADDRESS_OK"


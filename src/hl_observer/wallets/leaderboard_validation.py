from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel


FULL_WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TRUNCATED_WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{2,12}\.\.\.[a-fA-F0-9]{2,12}$")


class LeaderboardAddressStatus(StrEnum):
    FULL_ADDRESS_OK = "FULL_ADDRESS_OK"
    TRUNCATED_ADDRESS_REJECTED = "TRUNCATED_ADDRESS_REJECTED"
    INVALID_ADDRESS_REJECTED = "INVALID_ADDRESS_REJECTED"
    EMPTY_ADDRESS_REJECTED = "EMPTY_ADDRESS_REJECTED"
    SCREENSHOT_ONLY_REJECTED = "SCREENSHOT_ONLY_REJECTED"
    IMPORTED_FULL_ADDRESS_OK = "IMPORTED_FULL_ADDRESS_OK"
    DOM_FULL_ADDRESS_OK = "DOM_FULL_ADDRESS_OK"
    NETWORK_FULL_ADDRESS_OK = "NETWORK_FULL_ADDRESS_OK"
    NEEDS_MANUAL_IMPORT = "NEEDS_MANUAL_IMPORT"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class ValidationResult(BaseModel):
    raw_value: str
    normalized_value: str | None = None
    is_full_address: bool = False
    is_truncated: bool = False
    validation_status: LeaderboardAddressStatus
    rejection_reason: str | None = None


def is_full_wallet_address(value: str) -> bool:
    return bool(FULL_WALLET_RE.fullmatch(value.strip()))


def is_truncated_wallet_display(value: str) -> bool:
    return bool(TRUNCATED_WALLET_RE.fullmatch(value.strip()))


def validate_leaderboard_wallet_address(
    value: str | None,
    *,
    source_method: str = "import",
) -> ValidationResult:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return ValidationResult(
            raw_value=raw,
            validation_status=LeaderboardAddressStatus.EMPTY_ADDRESS_REJECTED,
            rejection_reason="empty_address",
        )
    if is_full_wallet_address(raw):
        if source_method == "network":
            status = LeaderboardAddressStatus.NETWORK_FULL_ADDRESS_OK
        elif source_method == "dom":
            status = LeaderboardAddressStatus.DOM_FULL_ADDRESS_OK
        elif source_method == "import":
            status = LeaderboardAddressStatus.IMPORTED_FULL_ADDRESS_OK
        else:
            status = LeaderboardAddressStatus.FULL_ADDRESS_OK
        return ValidationResult(
            raw_value=raw,
            normalized_value=raw.lower(),
            is_full_address=True,
            validation_status=status,
        )
    if is_truncated_wallet_display(raw) or "..." in raw:
        return ValidationResult(
            raw_value=raw,
            is_truncated=True,
            validation_status=LeaderboardAddressStatus.TRUNCATED_ADDRESS_REJECTED,
            rejection_reason="truncated_address_never_usable",
        )
    return ValidationResult(
        raw_value=raw,
        validation_status=LeaderboardAddressStatus.INVALID_ADDRESS_REJECTED,
        rejection_reason="not_42_char_hex_address",
    )


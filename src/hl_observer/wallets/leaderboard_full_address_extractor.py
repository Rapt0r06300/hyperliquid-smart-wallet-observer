from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from hl_observer.wallets.leaderboard_validation import (
    is_full_wallet_address,
    is_truncated_wallet_display,
)


ADDRESS_LIKE_RE = re.compile(r"0x[a-fA-F0-9]{2,40}(?:\.\.\.[a-fA-F0-9]{2,12})?")


@dataclass(frozen=True)
class ExtractedLeaderboardAddresses:
    full_addresses: list[str]
    truncated_addresses: list[str]
    rejected_values: list[str]


def extract_wallet_address_values(payload: Any) -> ExtractedLeaderboardAddresses:
    """Extract only observed address strings; never complete or synthesize addresses."""
    values = _walk_strings(payload)
    full: list[str] = []
    truncated: list[str] = []
    rejected: list[str] = []
    for value in values:
        for match in ADDRESS_LIKE_RE.findall(value):
            if is_full_wallet_address(match):
                full.append(match.lower())
            elif is_truncated_wallet_display(match) or "..." in match:
                truncated.append(match)
            else:
                rejected.append(match)
    return ExtractedLeaderboardAddresses(
        full_addresses=_dedupe(full),
        truncated_addresses=_dedupe(truncated),
        rejected_values=_dedupe(rejected),
    )


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            found.extend(_walk_strings(key))
            found.extend(_walk_strings(item))
        return found
    if isinstance(value, list | tuple | set):
        found = []
        for item in value:
            found.extend(_walk_strings(item))
        return found
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped

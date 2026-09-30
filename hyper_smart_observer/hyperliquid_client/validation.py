from __future__ import annotations

import re

WALLET_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def is_valid_wallet_address(address: str) -> bool:
    return bool(WALLET_ADDRESS_RE.fullmatch(address.strip()))


def normalize_wallet_address(address: str) -> str:
    normalized = address.strip().lower()
    if not is_valid_wallet_address(normalized):
        raise ValueError("Wallet address must be a full 42-character 0x hex address.")
    return normalized

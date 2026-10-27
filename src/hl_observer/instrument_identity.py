"""Venue-native instrument identity helpers shared across runtime layers."""

from __future__ import annotations

from typing import Any


def preserve_native_instrument_symbol(value: Any) -> str:
    """Trim an instrument identifier without changing its case or namespace."""

    return str(value or "").strip()


__all__ = ["preserve_native_instrument_symbol"]

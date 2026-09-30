from __future__ import annotations


def normalize_symbol(symbol: str) -> str:
    """Normalize venue symbols to HyperSmart coin notation."""

    raw = str(symbol or "").strip().upper()
    for suffix in ("-PERP", "PERP", "-USD", "/USD", "-USDT", "/USDT", "_USD", "_USDT"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return raw.replace("/", "-").replace("_", "-").strip("-")


__all__ = ["normalize_symbol"]

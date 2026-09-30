"""Symbol normalization shared by Bybit and OKX public feeds."""

from __future__ import annotations

KNOWN_QUOTES: tuple[str, ...] = ("USDT", "USDC", "USD")


def canonical_symbol(base: str, quote: str) -> str:
    base_clean = str(base or "").strip().upper()
    quote_clean = str(quote or "").strip().upper()
    if not base_clean or not quote_clean:
        raise ValueError("base and quote are required")
    return f"{base_clean}-{quote_clean}"


def split_bybit_symbol(symbol: str) -> tuple[str, str]:
    value = str(symbol or "").strip().upper()
    for quote in KNOWN_QUOTES:
        if value.endswith(quote) and len(value) > len(quote):
            return value[: -len(quote)], quote
    raise ValueError(f"unsupported Bybit symbol: {symbol!r}")


def canonical_bybit_symbol(symbol: str, *, base: str | None = None, quote: str | None = None) -> str:
    if base and quote:
        return canonical_symbol(base, quote)
    inferred_base, inferred_quote = split_bybit_symbol(symbol)
    return canonical_symbol(inferred_base, inferred_quote)


def split_okx_symbol(inst_id: str) -> tuple[str, str]:
    parts = str(inst_id or "").strip().upper().split("-")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"unsupported OKX instrument id: {inst_id!r}")
    return parts[0], parts[1]


def canonical_okx_symbol(inst_id: str) -> str:
    base, quote = split_okx_symbol(inst_id)
    return canonical_symbol(base, quote)


def base_from_canonical(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if "-" not in value:
        return value
    return value.split("-", 1)[0]


__all__ = [
    "KNOWN_QUOTES",
    "base_from_canonical",
    "canonical_bybit_symbol",
    "canonical_okx_symbol",
    "canonical_symbol",
    "split_bybit_symbol",
    "split_okx_symbol",
]

from __future__ import annotations


def regime_allows_paper(regime: str) -> bool:
    return regime.lower() not in {"panic", "halted", "unknown_bad"}

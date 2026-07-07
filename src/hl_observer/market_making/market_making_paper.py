"""Paper market-making quote generator, detection/simulation only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PaperMakerQuote:
    coin: str
    bid: float
    ask: float
    size_usdt: float
    paper_only: bool = True


def build_paper_maker_quote(*, coin: str, mid: float, spread_bps: float, size_usdt: float) -> PaperMakerQuote:
    half = float(spread_bps) / 20_000.0
    return PaperMakerQuote(str(coin).upper(), round(float(mid) * (1 - half), 10), round(float(mid) * (1 + half), 10), float(size_usdt))


__all__ = ["PaperMakerQuote", "build_paper_maker_quote"]

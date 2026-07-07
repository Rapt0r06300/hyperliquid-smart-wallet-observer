"""V15 #207 — Bounded multi-coin scan breadth (wider, but capped).

Wider breadth finds more fresh opportunities, but unbounded breadth wastes the rate budget
on noise. This selects a capped, de-duplicated coin set, always keeping must-include coins
and filling the rest by a priority order. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ScanBreadth:
    coins: tuple[str, ...]
    dropped: tuple[str, ...]
    capped: bool


def bounded_scan_breadth(
    candidate_coins_by_priority: Sequence[str],
    *,
    max_coins: int = 80,
    must_include: Sequence[str] = (),
) -> ScanBreadth:
    seen: set[str] = set()
    out: list[str] = []
    for c in must_include:
        cu = str(c).upper()
        if cu and cu not in seen:
            seen.add(cu); out.append(cu)
    dropped: list[str] = []
    for c in candidate_coins_by_priority:
        cu = str(c).upper()
        if not cu or cu in seen:
            continue
        if len(out) < max_coins:
            seen.add(cu); out.append(cu)
        else:
            dropped.append(cu)
    return ScanBreadth(tuple(out[:max_coins]), tuple(dropped), len(out) >= max_coins and bool(dropped))


__all__ = ["ScanBreadth", "bounded_scan_breadth"]

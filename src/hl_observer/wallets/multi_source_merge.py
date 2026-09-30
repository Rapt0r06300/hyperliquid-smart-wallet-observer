"""V14 #174 — Multi-source wallet fusion (explorer + WS firehose + leaderboard) + provenance.

Pure merge: dedupe by normalised address, union provenance sources, compute a combined
confidence (more independent sources + higher per-source score => higher), keep freshest
timestamp. read-only / paper-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

KNOWN_SOURCES = ("explorer", "ws_firehose", "leaderboard")


@dataclass(frozen=True, slots=True)
class WalletRef:
    address: str
    source: str
    score: float = 0.0     # 0..1 per-source confidence
    ts_ms: int = 0


@dataclass(frozen=True, slots=True)
class MergedWallet:
    address: str
    sources: tuple[str, ...]
    n_sources: int
    confidence: float      # 0..1
    best_score: float
    last_seen_ms: int


def _norm(addr: str) -> str:
    return str(addr or "").strip().lower()


def merge_wallet_sources(refs: Sequence[WalletRef]) -> list[MergedWallet]:
    """Dedupe by address; union sources; confidence rises with corroboration."""
    by_addr: dict[str, list[WalletRef]] = {}
    for r in refs:
        a = _norm(r.address)
        if not a:
            continue
        by_addr.setdefault(a, []).append(r)
    merged: list[MergedWallet] = []
    for addr, group in by_addr.items():
        sources = tuple(sorted({str(g.source or "unknown") for g in group}))
        best_score = max((float(g.score) for g in group), default=0.0)
        last_seen = max((int(g.ts_ms) for g in group), default=0)
        # corroboration boost: +12% per extra independent source, capped.
        boost = min(1.25, 1.0 + 0.12 * max(0, len(sources) - 1))
        confidence = max(0.0, min(1.0, best_score * boost))
        merged.append(MergedWallet(
            address=addr, sources=sources, n_sources=len(sources),
            confidence=round(confidence, 6), best_score=round(best_score, 6), last_seen_ms=last_seen,
        ))
    merged.sort(key=lambda m: (-m.n_sources, -m.confidence, -m.last_seen_ms))
    return merged


__all__ = ["KNOWN_SOURCES", "WalletRef", "MergedWallet", "merge_wallet_sources"]

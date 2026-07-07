"""GAP SCALE — Loader d'historique en masse (interface + fake déterministe).

Pour scorer des centaines de leaders et faire des backtests longs sans marteler
l'API HL, la source officielle est le bucket S3 (fills/funding historiques). Ce
module définit l'INTERFACE de chargement et un fake déterministe testable. Aucun
réseau ici: l'implémentation réelle (S3/HTTP) sera injectée derrière ce contrat.
"""

from __future__ import annotations

from typing import Protocol


class BulkHistorySource(Protocol):
    def load_fills(self, wallet: str, start_ms: int, end_ms: int) -> list[dict]: ...
    def load_funding(self, coin: str, start_ms: int, end_ms: int) -> list[dict]: ...


class FakeBulkHistory:
    """Source déterministe pour tests/CLI: données injectées, filtrées par fenêtre."""

    def __init__(self, fills: dict[str, list[dict]] | None = None, funding: dict[str, list[dict]] | None = None) -> None:
        self._fills = fills or {}
        self._funding = funding or {}

    def load_fills(self, wallet: str, start_ms: int, end_ms: int) -> list[dict]:
        rows = self._fills.get(str(wallet), [])
        return [r for r in rows if start_ms <= int(r.get("ts_ms", 0)) <= end_ms]

    def load_funding(self, coin: str, start_ms: int, end_ms: int) -> list[dict]:
        rows = self._funding.get(str(coin).upper(), [])
        return [r for r in rows if start_ms <= int(r.get("ts_ms", 0)) <= end_ms]


def load_many_wallets(source: BulkHistorySource, wallets: list[str], start_ms: int, end_ms: int) -> dict[str, list[dict]]:
    """Charge l'historique de plusieurs wallets (pour scoring de masse)."""
    return {w: source.load_fills(w, start_ms, end_ms) for w in (wallets or [])}


def coverage_report(loaded: dict[str, list[dict]]) -> dict:
    counts = {w: len(rows) for w, rows in loaded.items()}
    empty = [w for w, n in counts.items() if n == 0]
    return {
        "wallets": len(loaded),
        "with_data": sum(1 for n in counts.values() if n > 0),
        "empty": empty,
        "total_fills": sum(counts.values()),
    }


__all__ = ["BulkHistorySource", "FakeBulkHistory", "load_many_wallets", "coverage_report"]

"""Wallet thesis (V12, repo 13): a sourced narrative about a leader wallet (context only).

Requires at least one source; refuses to emit an unsourced thesis (no fabrication). Pure.
"""

from __future__ import annotations


def build_wallet_thesis(*, wallet: str, stats: dict, sources: list[str]) -> dict | None:
    if not sources:
        return None  # no fabricated thesis without sources
    pnl = stats.get("total_pnl_usdc")
    wr = stats.get("winrate")
    return {
        "wallet": wallet,
        "thesis": f"Wallet {wallet[:10]}…: winrate={wr}, pnl_usdc={pnl}",
        "sources": list(sources),
        "context_only": True,
    }


__all__ = ["build_wallet_thesis"]

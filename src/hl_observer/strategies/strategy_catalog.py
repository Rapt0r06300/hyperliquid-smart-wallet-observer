"""Small local strategy catalog."""

from __future__ import annotations

from hl_observer.strategies.external_github_bridge import external_strategy_catalog


def strategy_catalog() -> tuple[str, ...]:
    # External GitHub-inspired profiles are first by design: they are the
    # priority paper adapters. Internal engines remain as fallback strategies.
    return (
        *external_strategy_catalog(),
        "wallet_mirror_copy_follow",
        "cross_source_paper_arbitrage",
        "funding_paper_carry",
        "market_making_paper",
    )


__all__ = ["strategy_catalog"]

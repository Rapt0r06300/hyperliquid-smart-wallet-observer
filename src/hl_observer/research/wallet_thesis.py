"""Wallet thesis (V12, repo 13): a sourced narrative about a leader wallet (context only).

Requires at least one source; refuses to emit an unsourced thesis (no fabrication). Pure.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite


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


def regime_persistence_receipt(
    regime_results: Mapping[str, Mapping[str, object]],
    *,
    min_samples: int = 30,
) -> dict[str, object]:
    """Assess persistence without treating missing regimes as positive evidence."""
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples <= 0:
        return {"status": "UNMEASURABLE", "reason": "min_samples_must_be_positive_integer"}
    if not isinstance(regime_results, Mapping) or not regime_results:
        return {"status": "MORE_DATA", "reason": "regime_results_missing"}
    per_regime: dict[str, dict[str, object]] = {}
    missing = False
    rejected = False
    for name, result in regime_results.items():
        if not isinstance(result, Mapping):
            return {"status": "UNMEASURABLE", "reason": "regime_result_must_be_mapping"}
        samples = result.get("sample_count", result.get("samples"))
        net_pnl = result.get("net_pnl_usdc", result.get("net_pnl"))
        if isinstance(samples, bool) or not isinstance(samples, int) or samples < 0:
            return {"status": "UNMEASURABLE", "reason": f"invalid_sample_count:{name}"}
        if isinstance(net_pnl, bool) or not isinstance(net_pnl, (int, float)) or not isfinite(float(net_pnl)):
            per_regime[str(name)] = {"status": "MORE_DATA", "reason": "net_pnl_missing", "sample_count": samples}
            missing = True
            continue
        regime_status = "PROVEN" if samples >= min_samples and net_pnl > 0 else "MORE_DATA" if samples < min_samples else "REJECTED"
        per_regime[str(name)] = {
            "status": regime_status,
            "sample_count": samples,
            "net_pnl_usdc": float(net_pnl),
        }
        missing = missing or samples < min_samples
        rejected = rejected or regime_status == "REJECTED"
    if rejected:
        status = "REJECTED"
    elif missing:
        status = "MORE_DATA"
    else:
        status = "PROVEN"
    return {
        "status": status,
        "min_samples": min_samples,
        "regimes": per_regime,
        "stable_across_regimes": status == "PROVEN",
    }


__all__ = ["build_wallet_thesis", "regime_persistence_receipt"]

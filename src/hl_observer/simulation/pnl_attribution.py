from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from hl_observer.simulation.decision_replay_analyzer import ReplayAnalysis


@dataclass(frozen=True, slots=True)
class PnlAttribution:
    pnl_by_coin: dict[str, float]
    pnl_by_wallet: dict[str, float]
    best_coin: str | None
    worst_coin: str | None
    best_wallet: str | None
    worst_wallet: str | None


def build_pnl_attribution(analysis: ReplayAnalysis) -> PnlAttribution:
    return PnlAttribution(
        pnl_by_coin=analysis.pnl_by_coin,
        pnl_by_wallet=analysis.pnl_by_wallet,
        best_coin=_best_key(analysis.pnl_by_coin),
        worst_coin=_worst_key(analysis.pnl_by_coin),
        best_wallet=_best_key(analysis.pnl_by_wallet),
        worst_wallet=_worst_key(analysis.pnl_by_wallet),
    )


def format_pnl_attribution(attribution: PnlAttribution) -> str:
    lines = [
        "pnl_attribution=local_simulation",
        f"best_coin={attribution.best_coin}",
        f"worst_coin={attribution.worst_coin}",
        f"best_wallet={attribution.best_wallet}",
        f"worst_wallet={attribution.worst_wallet}",
    ]
    lines.append("pnl_by_coin:")
    lines.extend(f"- {coin}: {pnl:.6f}" for coin, pnl in sorted(attribution.pnl_by_coin.items()))
    lines.append("pnl_by_wallet:")
    lines.extend(f"- {wallet}: {pnl:.6f}" for wallet, pnl in sorted(attribution.pnl_by_wallet.items()))
    return "\n".join(lines)


def _best_key(values: dict[str, float]) -> str | None:
    if not values:
        return None
    return max(values, key=values.get)


def _worst_key(values: dict[str, float]) -> str | None:
    if not values:
        return None
    return min(values, key=values.get)


def partial_close_fee_receipt(closes: list[dict[str, Any]], *, residual_quantity: object) -> dict[str, object]:
    """Reconcile fees on partial closes while preserving the residual position."""
    if not isinstance(closes, list) or not closes or isinstance(residual_quantity, bool) or not isinstance(residual_quantity, (int, float)) or not math.isfinite(float(residual_quantity)) or float(residual_quantity) < 0:
        return {"status": "UNMEASURABLE", "reason": "PARTIAL_CLOSE_INPUT_INVALID"}
    allocated: list[float] = []
    quantities: list[float] = []
    for row in closes:
        if not isinstance(row, dict):
            return {"status": "UNMEASURABLE", "reason": "PARTIAL_CLOSE_ROW_INVALID"}
        quantity = row.get("quantity")
        fee = row.get("fee_usdc")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0 for value in (quantity, fee)):
            return {"status": "UNMEASURABLE", "reason": "PARTIAL_CLOSE_VALUE_INVALID"}
        quantities.append(float(quantity))
        allocated.append(float(fee))
    if sum(quantities) <= 0:
        return {"status": "UNMEASURABLE", "reason": "PARTIAL_CLOSE_QUANTITY_EMPTY"}
    return {"status": "PROVEN", "fees_by_close_usdc": [round(value, 10) for value in allocated], "total_close_fees_usdc": round(sum(allocated), 10), "closed_quantity": round(sum(quantities), 10), "residual_quantity": round(float(residual_quantity), 10), "residual_preserved": True}


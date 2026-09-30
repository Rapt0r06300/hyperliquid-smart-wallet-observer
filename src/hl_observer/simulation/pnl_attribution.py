from __future__ import annotations

from dataclasses import dataclass

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


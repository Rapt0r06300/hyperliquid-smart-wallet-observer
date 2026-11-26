"""Prioritize proven leaders in the read-only observation shortlist.

During warm-up, or when qualified leaders are outside the current candidate batch,
keep observing the candidates so the collector can acquire the history needed for
later evaluation. This fallback is for data acquisition only: it is not evidence
that a candidate is copy-eligible or economically validated.
"""

from __future__ import annotations

from hl_observer.scoring.leader_quality_gate import LeaderQualityConfig, assess_leader_quality


def qualified_wallets(
    moves_by_wallet: dict[str, list[float]],
    *,
    config: LeaderQualityConfig | None = None,
) -> set[str]:
    cfg = config or LeaderQualityConfig()
    canonical_moves: dict[str, list[float]] = {}
    for wallet, moves in moves_by_wallet.items():
        canonical_moves.setdefault(str(wallet).strip().casefold(), []).extend(moves)
    return {
        wallet
        for wallet, moves in canonical_moves.items()
        if wallet
        and assess_leader_quality(wallet, moves, config=cfg).qualified
    }


def filter_to_qualified(
    rows: list,
    moves_by_wallet: dict[str, list[float]],
    *,
    config: LeaderQualityConfig | None = None,
    min_qualified: int = 1,
):
    """Renvoie (rows_gardés, set_wallets_qualifiés).

    - En warm-up, renvoie les candidats pour continuer l'observation.
    - Avec assez d'historique, préfère uniquement les wallets qualifiés.
    - Si les qualifiés ne figurent pas dans ce lot, conserve le lot pour l'observation.
    """
    qualified = qualified_wallets(moves_by_wallet, config=config)
    if len(qualified) < max(1, int(min_qualified)):
        return list(rows), qualified
    kept = [
        row
        for row in rows
        if str(getattr(row, "wallet_address", None) or "").strip().casefold() in qualified
    ]
    return (kept if kept else list(rows)), qualified


__all__ = ["qualified_wallets", "filter_to_qualified"]

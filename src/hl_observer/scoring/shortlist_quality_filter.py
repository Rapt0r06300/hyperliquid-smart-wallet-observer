"""V9 — Filtre de qualité de la shortlist (le levier PnL, branché).

Ne garde, parmi les leaders candidats, que ceux dont la qualité RÉALISÉE est prouvée
(via leader_quality_gate). Sécurité « warmup » : tant qu'aucun leader n'a assez
d'historique pour qualifier, on NE coupe PAS la shortlist (le bot continue d'observer
et d'accumuler de l'historique au lieu de geler). read-only / paper-only.
"""

from __future__ import annotations

from hl_observer.scoring.leader_quality_gate import LeaderQualityConfig, assess_leader_quality


def qualified_wallets(
    moves_by_wallet: dict[str, list[float]],
    *,
    config: LeaderQualityConfig | None = None,
) -> set[str]:
    cfg = config or LeaderQualityConfig()
    return {
        wallet
        for wallet, moves in moves_by_wallet.items()
        if assess_leader_quality(wallet, moves, config=cfg).qualified
    }


def filter_to_qualified(
    rows: list,
    moves_by_wallet: dict[str, list[float]],
    *,
    config: LeaderQualityConfig | None = None,
    min_qualified: int = 1,
):
    """Renvoie (rows_gardés, set_wallets_qualifiés).

    - Si < min_qualified leaders qualifiés (warmup) -> renvoie TOUS les rows (ne gèle pas).
    - Sinon -> ne garde que les rows dont le wallet est qualifié (copie étroite).
    - Si le filtre vide la liste (qualifiés hors candidats) -> repli sur tous les rows.
    """
    qualified = qualified_wallets(moves_by_wallet, config=config)
    if len(qualified) < max(1, int(min_qualified)):
        return list(rows), qualified
    kept = [r for r in rows if getattr(r, "wallet_address", None) in qualified]
    return (kept if kept else list(rows)), qualified


__all__ = ["qualified_wallets", "filter_to_qualified"]

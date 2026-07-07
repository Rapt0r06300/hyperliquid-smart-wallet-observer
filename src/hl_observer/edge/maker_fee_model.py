"""F1 — Modèle maker-first : payer le frais maker (post-only) au lieu du taker.

Le fee drag est un frein PnL majeur. Une entrée post-only paie ~2 bps (maker) au lieu
de ~5 (taker), MAIS avec un risque de non-fill à modéliser. Pur.
"""

from __future__ import annotations


def effective_fee_bps(*, post_only: bool, maker_fee_bps: float = 2.0, taker_fee_bps: float = 5.0) -> float:
    return float(maker_fee_bps) if post_only else float(taker_fee_bps)


def maker_saving_bps(*, maker_fee_bps: float = 2.0, taker_fee_bps: float = 5.0) -> float:
    """Économie par jambe en passant maker (round-trip = x2)."""
    return max(0.0, float(taker_fee_bps) - float(maker_fee_bps))


def expected_maker_edge_bps(gross_edge_bps: float, *, maker_fill_prob: float = 0.6,
                            maker_fee_bps: float = 2.0, taker_fee_bps: float = 5.0) -> float:
    """Edge attendu en maker-first : (prob de fill) × (edge - frais maker round-trip).
    Si non rempli, 0 (pas de position). Aide à décider maker vs taker."""
    p = max(0.0, min(1.0, maker_fill_prob))
    net_if_filled = gross_edge_bps - 2.0 * float(maker_fee_bps)
    return round(p * net_if_filled, 6)


__all__ = ["effective_fee_bps", "maker_saving_bps", "expected_maker_edge_bps"]

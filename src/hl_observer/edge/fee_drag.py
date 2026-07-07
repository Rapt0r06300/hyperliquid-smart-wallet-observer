"""F14 — Moniteur de fee drag : les frais mangent-ils l'edge ? Pur."""

from __future__ import annotations


def fee_drag_ratio(total_fees_bps: float, gross_edge_bps: float) -> float:
    """Part de l'edge brut consommée par les frais. >1 = frais > edge (perte structurelle)."""
    if gross_edge_bps <= 0:
        return 1e9 if total_fees_bps > 0 else 0.0
    return round(float(total_fees_bps) / float(gross_edge_bps), 6)


def fee_drag_too_high(total_fees_bps: float, gross_edge_bps: float, *, max_ratio: float = 0.5) -> tuple[bool, str]:
    """Vrai si les frais consomment plus de max_ratio de l'edge brut -> réduire la fréquence."""
    r = fee_drag_ratio(total_fees_bps, gross_edge_bps)
    if r > float(max_ratio):
        return True, f"FEE_DRAG_TOO_HIGH(ratio={r})"
    return False, "OK"


__all__ = ["fee_drag_ratio", "fee_drag_too_high"]

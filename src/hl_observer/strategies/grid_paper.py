"""GAP P4 — Grid/MM paper cappé (distillé passivbot, SANS martingale infinie).

passivbot fait beaucoup de micro-fills maker en grille + re-entrées à la baisse.
Le danger = martingale (doubler indéfiniment sur les pertes). Ici: grille bornée,
nombre de re-entrées CAPPÉ, exposition totale CAPPÉE, taille de re-entrée NON
croissante (jamais de doublement). 100% paper, flag OFF par défaut. Pur.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ENV_ENABLED = "HYPERSMART_GRID_PAPER"


def grid_paper_enabled() -> bool:
    return str(os.getenv(ENV_ENABLED, "0")).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class GridLevel:
    index: int
    price: float
    size_usdt: float
    take_profit_price: float


def build_grid(
    *, mid_price: float, side: str = "LONG",
    levels: int = 5, step_pct: float = 0.8, base_size_usdt: float = 10.0,
    tp_markup_pct: float = 0.6, max_reentries: int = 5, max_total_usdt: float = 60.0,
) -> dict:
    """Construit une grille bornée. Refuse toute config qui ressemble à une martingale."""

    side = str(side).upper()
    if side not in {"LONG", "SHORT"} or mid_price <= 0 or levels <= 0:
        return {"ok": False, "reason": "INVALID_GRID_INPUTS", "levels": []}
    n = min(int(levels), int(max_reentries))
    out: list[GridLevel] = []
    total = 0.0
    for i in range(n):
        # grille contrarian: LONG achète SOUS le mid, SHORT vend AU-DESSUS
        offset = (i + 1) * step_pct / 100.0
        price = mid_price * (1 - offset) if side == "LONG" else mid_price * (1 + offset)
        size = base_size_usdt   # TAILLE CONSTANTE: jamais de doublement (anti-martingale)
        if total + size > max_total_usdt:
            break
        tp = price * (1 + tp_markup_pct / 100.0) if side == "LONG" else price * (1 - tp_markup_pct / 100.0)
        out.append(GridLevel(i, round(price, 8), round(size, 4), round(tp, 8)))
        total += size
    levels_dicts = [
        {"index": l.index, "price": l.price, "size_usdt": l.size_usdt, "take_profit_price": l.take_profit_price}
        for l in out
    ]
    return {
        "ok": True, "side": side, "levels": levels_dicts,
        "level_count": len(out), "total_notional_usdt": round(total, 4),
        "anti_martingale": True, "reason": "GRID_BOUNDED",
        "paper_only": True, "real_execution": False,
    }


def validate_no_martingale(grid: dict) -> bool:
    """Vrai si aucune taille de niveau n'augmente (pas d'averaging-down agressif)."""
    sizes = [float(l["size_usdt"]) for l in grid.get("levels", [])]
    return all(sizes[i] <= sizes[i - 1] for i in range(1, len(sizes)))


__all__ = ["ENV_ENABLED", "grid_paper_enabled", "GridLevel", "build_grid", "validate_no_martingale"]

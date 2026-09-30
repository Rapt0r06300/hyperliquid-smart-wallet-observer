"""V13 #158 — Stress test (paper): PnL des positions ouvertes sous un choc de prix.

Combien perdrait/gagnerait le portefeuille PAPER si le prix bougeait de X% d'un coup ?
Pur / lecture seule : aucune position réelle, aucun ordre.
"""

from __future__ import annotations


def _notional(p: dict) -> float:
    return abs(float(p.get("notional_usdt") or p.get("notional_usdc")
                      or p.get("open_exposure_usdt") or p.get("size_usdt") or 0.0))


def stress_pnl(positions: list[dict], *, shock_pct: float) -> float:
    """PnL total (USDC) si le prix bouge de shock_pct (+ = hausse). LONG gagne, SHORT perd."""
    total = 0.0
    for p in positions or []:
        side = str(p.get("side") or p.get("direction") or "").upper()
        notional = _notional(p)
        direction = 1.0 if side in {"LONG", "BUY"} else (-1.0 if side in {"SHORT", "SELL"} else 0.0)
        total += direction * notional * float(shock_pct)
    return round(total, 6)


def stress_scenarios(positions: list[dict],
                     shocks=(-0.10, -0.05, -0.02, 0.02, 0.05, 0.10)) -> list[dict]:
    return [{"shock_pct": round(s, 4), "pnl_usdc": stress_pnl(positions, shock_pct=s)} for s in shocks]


def worst_case(positions: list[dict], shocks=(-0.10, -0.05, -0.02, 0.02, 0.05, 0.10)) -> dict:
    scen = stress_scenarios(positions, shocks)
    if not scen:
        return {"shock_pct": 0.0, "pnl_usdc": 0.0}
    return min(scen, key=lambda s: s["pnl_usdc"])


__all__ = ["stress_pnl", "stress_scenarios", "worst_case"]

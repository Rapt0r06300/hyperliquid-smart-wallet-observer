"""V13 #158 — Panneau risque PAPER (lecture seule), langage simple.

Compose : VaR/CVaR (risk.var_cvar) sur les derniers trades réels, stress test
(risk.stress_test) sur les positions ouvertes, alertes de seuils (risk.breach_alerts) et
disjoncteur (kill switch). Phrases claires pour débutant ; état vide honnête ; 0 ordre.
"""

from __future__ import annotations

from hl_observer.risk.breach_alerts import check_breaches
from hl_observer.risk.stress_test import worst_case
from hl_observer.risk.var_cvar import historical_cvar, historical_var


def build_risk_panel(
    *,
    recent_trade_pnls: list[float] | None = None,
    open_positions: list[dict] | None = None,
    equity: float | None = None,
    start_equity: float = 1000.0,
    daily_loss_pct: float = 0.0,
    kill_switch_tripped: bool = False,
    confidence: float = 0.95,
) -> dict:
    pnls = [float(x) for x in (recent_trade_pnls or [])]
    positions = list(open_positions or [])

    var = historical_var(pnls, confidence=confidence) if len(pnls) >= 2 else None
    cvar = historical_cvar(pnls, confidence=confidence) if len(pnls) >= 2 else None
    worst = worst_case(positions) if positions else None
    exposure = round(sum(abs(float(p.get("notional_usdt") or p.get("open_exposure_usdt") or 0.0))
                         for p in positions), 2)

    total_loss_pct = 0.0
    if equity is not None and start_equity > 0:
        total_loss_pct = max(0.0, (float(start_equity) - float(equity)) / float(start_equity) * 100.0)

    alerts = check_breaches(daily_loss_pct=daily_loss_pct, total_loss_pct=total_loss_pct)
    breached = [a for a in alerts if str(a.get("level", "")).upper() == "BREACH"]
    halted = bool(kill_switch_tripped) or total_loss_pct >= 40.0 or bool(breached)

    empty = len(pnls) < 2 and not positions and equity is None
    if empty:
        plain = ("Pas encore assez de trades pour mesurer le risque. Le panneau se remplira "
                 "au fil de la simulation.")
    else:
        bits = []
        if var is not None:
            bits.append(f"95% du temps, une perte sur un trade ne dépasse pas {var:.2f} $")
        if worst is not None:
            bits.append(f"dans le pire choc simulé ({int(worst['shock_pct']*100)}%), "
                        f"le portefeuille bougerait de {worst['pnl_usdc']:.2f} $")
        bits.append("disjoncteur DÉCLENCHÉ (trading en pause)" if halted else "disjoncteur OK")
        plain = "Risque : " + " ; ".join(bits) + "."

    return {
        "var_usdc": None if var is None else round(var, 4),
        "cvar_usdc": None if cvar is None else round(cvar, 4),
        "confidence": confidence,
        "worst_case": worst,
        "open_exposure_usdc": exposure,
        "total_loss_pct": round(total_loss_pct, 4),
        "halted": halted,
        "alerts": alerts,
        "n_trades": len(pnls),
        "plain_summary": plain,
        "empty": empty,
        "context_only": True,
    }


__all__ = ["build_risk_panel"]

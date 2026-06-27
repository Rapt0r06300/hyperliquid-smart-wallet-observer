"""Risk breach alerts (V12, repo 03): informational alerts on the 4-layer loss protection.

Daily 5% / monthly 15% / drawdown 25% / total 40% (defaults). Produces ALERTS only — the
actual halting is done by loss_halts; this surfaces what's approaching/breached. No action.
"""

from __future__ import annotations

_DEFAULTS = {"daily": 5.0, "monthly": 15.0, "drawdown": 25.0, "total": 40.0}


def check_breaches(*, daily_loss_pct: float = 0.0, monthly_loss_pct: float = 0.0,
                   drawdown_pct: float = 0.0, total_loss_pct: float = 0.0,
                   thresholds: dict | None = None, warn_ratio: float = 0.8) -> list[dict]:
    t = {**_DEFAULTS, **(thresholds or {})}
    values = {"daily": daily_loss_pct, "monthly": monthly_loss_pct,
              "drawdown": drawdown_pct, "total": total_loss_pct}
    alerts: list[dict] = []
    for layer, val in values.items():
        limit = float(t[layer])
        v = abs(float(val))
        if v >= limit:
            alerts.append({"layer": layer, "value_pct": v, "limit_pct": limit,
                           "severity": "BREACH", "action": "none (loss_halts decides)"})
        elif v >= limit * float(warn_ratio):
            alerts.append({"layer": layer, "value_pct": v, "limit_pct": limit, "severity": "WARN"})
    return alerts


__all__ = ["check_breaches"]

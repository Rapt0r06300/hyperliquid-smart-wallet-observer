"""A5 — Adaptateur runtime du risk gate (deny-by-default OFF).

Compose un `risk_fn` existant avec le risk gate portefeuille (halts/DD/VaR/streak).
L'état portefeuille est fourni par le runtime via `set_risk_state`. Tant que
HYPERSMART_RISK_GATE_ENABLED n'est pas activé, le comportement est inchangé.
Bloque des ENTRÉES paper ; ne touche jamais un ordre réel.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from hl_observer.risk.risk_gate import RiskGateConfig, RiskGateState, evaluate_risk_gate

FLAG = "HYPERSMART_RISK_GATE_ENABLED"
_STATE = RiskGateState()


def set_risk_state(state: RiskGateState) -> None:
    """Le runtime met à jour l'état portefeuille (perte jour, drawdown, streak…)."""
    global _STATE
    _STATE = state


def risk_gate_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(FLAG, "0")).lower() in ("1", "true", "yes")


def _config_from_env(env: dict | None = None) -> RiskGateConfig:
    e = env if env is not None else os.environ

    def _f(name: str, default: float) -> float:
        v = e.get(name)
        try:
            return float(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    return RiskGateConfig(
        max_daily_loss_pct=_f("HYPERSMART_RISK_MAX_DAILY_LOSS_PCT", 5.0),
        max_monthly_loss_pct=_f("HYPERSMART_RISK_MAX_MONTHLY_LOSS_PCT", 15.0),
        max_drawdown_pct=_f("HYPERSMART_RISK_MAX_DRAWDOWN_PCT", 20.0),
        max_loss_streak=int(_f("HYPERSMART_RISK_MAX_LOSS_STREAK", 5)),
    )


def risk_gate_check(env: dict | None = None) -> tuple[bool, tuple[str, ...]]:
    """(ok, reasons) du risk gate. Flag OFF -> (True, ())."""
    if not risk_gate_enabled(env):
        return True, ()
    v = evaluate_risk_gate(_STATE, _config_from_env(env))
    return v.ok, v.reasons


def compose_risk_fn(
    base_risk_fn: Callable[[object], tuple[bool, object]],
    *,
    env: dict | None = None,
) -> Callable[[object], tuple[bool, tuple[str, ...]]]:
    """Renvoie un risk_fn = base ET risk_gate (quand activé)."""

    def _fn(intent: object) -> tuple[bool, tuple[str, ...]]:
        ok, reasons = base_risk_fn(intent)
        g_ok, g_reasons = risk_gate_check(env)
        return bool(ok) and bool(g_ok), tuple(reasons or ()) + tuple(g_reasons)

    return _fn


__all__ = ["FLAG", "set_risk_state", "risk_gate_enabled", "risk_gate_check", "compose_risk_fn"]

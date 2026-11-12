"""A5 — Adaptateur runtime du risk gate (deny-by-default OFF).

Compose un `risk_fn` existant avec le risk gate portefeuille (halts/DD/VaR/streak).
L'état portefeuille est fourni par le runtime via `set_risk_state`. Tant que
HYPERSMART_RISK_GATE_ENABLED n'est pas activé, le comportement est inchangé.
Bloque des ENTRÉES paper ; ne touche jamais un ordre réel.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from hl_observer.risk.risk_gate import RiskGateConfig, RiskGateState, evaluate_risk_gate

FLAG = "HYPERSMART_RISK_GATE_ENABLED"
_STATE = RiskGateState()
_STATE_CONFIGURED = False
_ENTRY_ACTIONS = frozenset({"OPEN", "ADD", "ENTER", "BUY", "SELL"})
_CLOSE_ACTIONS = frozenset({"REDUCE", "CLOSE", "EXIT"})


def set_risk_state(state: RiskGateState) -> None:
    """Le runtime met à jour l'état portefeuille (perte jour, drawdown, streak…)."""
    global _STATE, _STATE_CONFIGURED
    _STATE = state
    _STATE_CONFIGURED = True


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
            return float("nan")

    def _i(name: str, default: int) -> int:
        v = e.get(name)
        try:
            return int(float(v)) if v not in (None, "") else default
        except (TypeError, ValueError, OverflowError):
            return -1

    return RiskGateConfig(
        max_daily_loss_pct=_f("HYPERSMART_RISK_MAX_DAILY_LOSS_PCT", 5.0),
        max_monthly_loss_pct=_f("HYPERSMART_RISK_MAX_MONTHLY_LOSS_PCT", 15.0),
        max_drawdown_pct=_f("HYPERSMART_RISK_MAX_DRAWDOWN_PCT", 20.0),
        max_loss_streak=_i("HYPERSMART_RISK_MAX_LOSS_STREAK", 5),
    )


def risk_gate_check(env: dict | None = None) -> tuple[bool, tuple[str, ...]]:
    """(ok, reasons) du risk gate. Flag OFF -> (True, ())."""
    if not risk_gate_enabled(env):
        return True, ()
    if not _STATE_CONFIGURED or not isinstance(_STATE, RiskGateState):
        return False, ("RISK_STATE_UNAVAILABLE",)
    try:
        v = evaluate_risk_gate(_STATE, _config_from_env(env))
    except Exception:
        return False, ("RISK_GATE_EVALUATION_UNAVAILABLE",)
    return v.ok, v.reasons


def source_staleness_check(intent: object) -> tuple[bool, tuple[str, ...]]:
    """Block new exposure on an explicit stale-source defect, close-only otherwise."""
    values: Mapping[str, object] | None = intent if isinstance(intent, Mapping) else None
    if values is None:
        return True, ()
    stale = values.get("source_stale") is True or values.get("stale_source") is True
    if not stale:
        return True, ()
    action = str(values.get("action") or values.get("side") or "").strip().upper()
    if action in _CLOSE_ACTIONS:
        return True, ("SOURCE_STALE_CLOSE_ONLY",)
    if action in _ENTRY_ACTIONS:
        return False, ("SOURCE_STALE_ENTRY_BLOCKED",)
    return False, ("SOURCE_STALE_UNKNOWN_ACTION_BLOCKED",)


def compose_risk_fn(
    base_risk_fn: Callable[[object], tuple[bool, object]],
    *,
    env: dict | None = None,
) -> Callable[[object], tuple[bool, tuple[str, ...]]]:
    """Renvoie un risk_fn = base ET risk_gate (quand activé)."""

    def _fn(intent: object) -> tuple[bool, tuple[str, ...]]:
        ok, reasons = base_risk_fn(intent)
        g_ok, g_reasons = risk_gate_check(env)
        source_ok, source_reasons = source_staleness_check(intent)
        return (
            bool(ok) and bool(g_ok) and bool(source_ok),
            tuple(reasons or ()) + tuple(g_reasons) + tuple(source_reasons),
        )

    return _fn


__all__ = [
    "FLAG",
    "set_risk_state",
    "risk_gate_enabled",
    "risk_gate_check",
    "source_staleness_check",
    "compose_risk_fn",
]

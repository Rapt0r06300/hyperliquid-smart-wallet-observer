"""A2 — Adaptateur runtime du gate d'entrée (deny-by-default OFF).

Fournit un `gate_fn(intent)->(ok, reasons)` à composer avec
`strategies.models.approve_with_risk_and_gate`. Tant que
HYPERSMART_ENTRY_GATE_ENABLED n'est pas activé, le gate est **inactif** (allow),
donc aucun changement de comportement. Read-only / paper. Un NO_TRADE n'est pas un ordre.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from hl_observer.signals.entry_gate_v2 import EntryGateInputs, evaluate_entry_gate

FLAG = "HYPERSMART_ENTRY_GATE_ENABLED"


def entry_gate_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(FLAG, "0")).lower() in ("1", "true", "yes")


def entry_gate_decision(context: dict, *, env: dict | None = None) -> tuple[bool, tuple[str, ...]]:
    """Décision (ok, reasons) depuis un contexte déjà calculé par le runtime.
    Flag OFF -> (True, ()) : le pipeline actuel n'est pas modifié."""
    if not entry_gate_enabled(env):
        return True, ()
    c = context or {}
    inp = EntryGateInputs(
        signal_freshness_score=float(c.get("signal_freshness_score", 1.0)),
        edge_net_bps=float(c.get("edge_net_bps", 0.0)),
        min_edge_bps=float(c.get("min_edge_bps", 30.0)),
        liquidity_ok=bool(c.get("liquidity_ok", True)),
        calibrated=bool(c.get("calibrated", True)),
        obi_confirms=bool(c.get("obi_confirms", True)),
        require_obi=bool(c.get("require_obi", False)),
        fill_confirmed=bool(c.get("fill_confirmed", True)),
        leader_consensus=int(c.get("leader_consensus", 1)),
        min_consensus=int(c.get("min_consensus", 1)),
        conflict=bool(c.get("conflict", False)),
    )
    v = evaluate_entry_gate(inp)
    return v.accepted, v.reasons


def make_gate_fn(
    context_provider: Callable[[object], dict],
    *,
    env: dict | None = None,
) -> Callable[[object], tuple[bool, tuple[str, ...]]] | None:
    """Construit un gate_fn(intent)->(ok, reasons) pour approve_with_risk_and_gate.
    Retourne None si le flag est OFF (le chokepoint se comporte alors comme avant)."""
    if not entry_gate_enabled(env):
        return None

    def _gate(intent: object) -> tuple[bool, tuple[str, ...]]:
        ctx = context_provider(intent) or {}
        return entry_gate_decision(ctx, env=env)

    return _gate


__all__ = ["FLAG", "entry_gate_enabled", "entry_gate_decision", "make_gate_fn"]

"""A4 — Adaptateur runtime de la politique d'exit (deny-by-default OFF).

Enrobe `exits.exit_policy.evaluate_exit` avec une config lue depuis l'environnement.
Tant que HYPERSMART_EXIT_POLICY_ENABLED n'est pas activé, `evaluate_exit_from_env`
renvoie None (aucun exit forcé par la politique → comportement inchangé).
Read-only / paper : un exit est une décision paper, jamais un ordre.
"""

from __future__ import annotations

from hl_observer.exits.exit_policy import (
    ExitDecision,
    evaluate_exit,
    exit_policy_config_from_env,
)


def evaluate_exit_from_env(
    *,
    side: str,
    entry_price: float,
    mark_price: float,
    best_price: float,
    age_ms: int,
    atr_bps: float | None = None,
    env: dict | None = None,
) -> ExitDecision | None:
    """Décision d'exit composée si la politique est activée, sinon None."""
    cfg = exit_policy_config_from_env(env)
    if cfg is None:
        return None
    return evaluate_exit(
        side=side,
        entry_price=entry_price,
        mark_price=mark_price,
        best_price=best_price,
        age_ms=age_ms,
        config=cfg,
        atr_bps=atr_bps,
    )


__all__ = ["evaluate_exit_from_env"]

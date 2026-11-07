"""ENG-070 — Assert paper-only fail-closed au démarrage moteur.

Refuse de démarrer si un flag mainnet/testnet vaut 1.
Journalise l'état des 4 invariants sécurité (ENG-071).
"""
from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

_INVARIANTS = {
    "HL_ENV": "paper",
    "HL_ENABLE_MAINNET_EXECUTION": "0",
    "HL_ENABLE_TESTNET_EXECUTION": "0",
    "HYPERSMART_MODE": "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW",
}


class PaperInvariantViolation(RuntimeError):
    pass


def assert_paper_only(*, log: bool = True) -> None:
    """Vérifie et journalise les invariants PAPER. Lève si violation."""
    violations: list[str] = []
    for var, expected in _INVARIANTS.items():
        actual = os.environ.get(var, "")
        status = "OK" if actual == expected else "VIOLATION"
        if log:
            logger.info("SECURITY_INVARIANT %s=%s (attendu=%s) [%s]", var, actual, expected, status)
        if status == "VIOLATION":
            violations.append(f"{var}={actual!r} (attendu {expected!r})")

    if violations:
        msg = "PAPER invariant violated — refuse de démarrer: " + "; ".join(violations)
        logger.critical(msg)
        raise PaperInvariantViolation(msg)

    if log:
        logger.info("SECURITY: 4/4 invariants PAPER vérifiés — mode read-only confirmé")


def is_paper_safe() -> bool:
    """Version non-bloquante pour les checks conditionnels."""
    try:
        assert_paper_only(log=False)
        return True
    except PaperInvariantViolation:
        return False


__all__ = [
    "PaperInvariantViolation",
    "assert_paper_only",
    "is_paper_safe",
]

"""Local decision layer for HyperSmart.

G2 : `noyau_unique` est LE point de decision. `local_engine` le consulte pour toute ENTREE
(jamais pour une sortie -- bloquer une sortie piegerait une position ouverte).
"""

# Le noyau AVANT local_engine : local_engine l'importe, et cet ordre evite toute ambiguite
# d'initialisation partielle du paquet.
from hl_observer.decision_engine import noyau_unique
from hl_observer.decision_engine.local_engine import (
    NOYAU_FLAG,
    DecisionAction,
    LocalDecision,
    LocalDecisionEngine,
    noyau_autoritaire,
)
from hl_observer.decision_engine.noyau_unique import Contexte, Decision, decider

__all__ = [
    "DecisionAction",
    "LocalDecision",
    "LocalDecisionEngine",
    "NOYAU_FLAG",
    "noyau_autoritaire",
    "noyau_unique",
    "Contexte",
    "Decision",
    "decider",
]

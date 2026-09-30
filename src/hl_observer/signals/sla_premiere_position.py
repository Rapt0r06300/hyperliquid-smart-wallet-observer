"""AUD-126 — SLA « premiere position OU diagnostic definitif » (jamais un silence).

Contrat NOMME : a tout instant, soit au moins une position paper a ete ouverte, soit un DIAGNOSTIC
DEFINITIF explique l'absence (bottleneck SUPPLY/GATES + next_action de entry_supply_diagnostics ;
ou readiness data de ready_strategies_diagnostic). Verdict SLA unique. Read-only, paper.
"""
from __future__ import annotations

from typing import Any

SLA_OK_POSITION = "SLA_OK_POSITION_OUVERTE"
SLA_OK_DIAGNOSTIC = "SLA_OK_DIAGNOSTIC_DEFINITIF"
SLA_VIOLE = "SLA_VIOLE_SILENCE"


def evaluer_sla(*, positions_ouvertes: int, diagnostic: Any) -> dict:
    """Respecte ssi une position existe OU un diagnostic definitif (non vide) est fourni. VIOLE si
    0 position ET aucun diagnostic (silence interdit)."""
    if int(positions_ouvertes) > 0:
        return {"sla": SLA_OK_POSITION, "respecte": True}
    a_diag = diagnostic is not None and str(diagnostic).strip() != "" and diagnostic != {}
    if a_diag:
        return {"sla": SLA_OK_DIAGNOSTIC, "respecte": True, "diagnostic": diagnostic}
    return {"sla": SLA_VIOLE, "respecte": False,
            "raison": "0 position ET aucun diagnostic definitif : silence interdit"}


__all__ = ["evaluer_sla", "SLA_OK_POSITION", "SLA_OK_DIAGNOSTIC", "SLA_VIOLE"]

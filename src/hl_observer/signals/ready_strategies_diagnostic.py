"""AUD-104 — READY_STRATEGIES expose au diagnostic, notamment en presence de ZERO position.

Quand aucune position n'est ouverte, il faut savoir POURQUOI par famille : soit la famille n'est
pas data-ready (une source requise manque -> on attend la donnee), soit elle EST ready mais n'ouvre
pas (chercher ailleurs : edge/sizing/scope). Ce module CONSOMME `strategy_readiness` (jusque-la non
appele au runtime) pour produire un diagnostic READY_STRATEGIES exploitable (status/UI). Read-only.
"""
from __future__ import annotations

from typing import Any

from hl_observer.strategies.strategy_readiness import ready_strategies

DIAG_POSITIONS = "POSITIONS_OUVERTES"
DIAG_READY_ZERO = "READY_MAIS_ZERO_POSITION"
DIAG_NO_DATA = "AUCUNE_FAMILLE_DATA_READY"


def diagnostic_ready_strategies(source_states: Any, *, positions_ouvertes: int = 0,
                                warmup: Any | None = None) -> dict:
    r = ready_strategies(source_states, warmup=warmup)
    pretes = sorted(f for f, x in r.items() if x.ready)
    bloquees = {f: sorted(x.missing_sources) for f, x in r.items() if not x.ready}
    if int(positions_ouvertes) > 0:
        diag = DIAG_POSITIONS
    elif pretes:
        diag = DIAG_READY_ZERO
    else:
        diag = DIAG_NO_DATA
    return {"diagnostic": diag, "familles_pretes": pretes, "familles_bloquees": bloquees,
            "positions_ouvertes": int(positions_ouvertes),
            "par_famille": {f: {"ready": x.ready, "raison": x.raison} for f, x in r.items()}}


__all__ = ["diagnostic_ready_strategies", "DIAG_POSITIONS", "DIAG_READY_ZERO", "DIAG_NO_DATA"]

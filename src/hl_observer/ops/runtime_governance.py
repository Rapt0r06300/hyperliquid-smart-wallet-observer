"""Runtime governance: fail-closed drift evidence and one canonical orchestrator."""

from __future__ import annotations

import math
from typing import Mapping

CANONIQUE = "historical_analysis_suite"


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def detecter_derive_execution(
    baseline: Mapping[str, float],
    courant: Mapping[str, float],
    *,
    tolerance: float = 0.20,
) -> dict:
    """Compare execution metrics; invalid evidence is itself an unstable no-go."""
    tol = _finite(tolerance)
    derives: dict[str, dict[str, float | str]] = {}
    if tol is None or tol < 0.0:
        return {"stable": False, "derives": {"__config__": {"reason": "TOLERANCE_INVALID"}}}
    if not baseline:
        return {"stable": False, "derives": {"__baseline__": {"reason": "BASELINE_MISSING"}}}
    for key, raw_base in baseline.items():
        base = _finite(raw_base)
        current = _finite(courant.get(key, raw_base))
        if base is None or current is None:
            derives[str(key)] = {"reason": "METRIC_UNMEASURED"}
            continue
        reference = abs(base) if base else 1e-9
        deviation = abs(current - base) / reference
        if not math.isfinite(deviation) or deviation > tol:
            derives[str(key)] = {
                "baseline": base,
                "courant": current,
                "ecart_relatif": round(deviation, 4) if math.isfinite(deviation) else "NONFINITE",
            }
    return {"stable": not derives, "derives": derives}


class RegistreOrchestrateurs:
    """Single-writer registry: a second canonical orchestrator is refused."""

    def __init__(self, canonique: str = CANONIQUE) -> None:
        if not str(canonique).strip():
            raise ValueError("canonical orchestrator is required")
        self._canonique = str(canonique)
        self._enregistres: dict[str, str] = {}

    def enregistrer(self, nom: str, role: str = "secondaire") -> None:
        name, normalized_role = str(nom).strip(), str(role).strip().lower()
        if not name:
            raise ValueError("orchestrator name is required")
        if normalized_role not in {"canonique", "secondaire"}:
            raise ValueError("orchestrator role is invalid")
        if normalized_role == "canonique" and name != self._canonique:
            raise PermissionError("parallel canonical orchestrator refused")
        previous = self._enregistres.get(name)
        if previous is not None and previous != normalized_role:
            raise PermissionError("orchestrator role mutation refused")
        self._enregistres[name] = normalized_role

    def canonique(self) -> str:
        return self._canonique

    def verifier_unicite(self) -> dict:
        canoniques = [name for name, role in self._enregistres.items() if role == "canonique"]
        unifie = canoniques == [self._canonique]
        return {
            "unifie": unifie,
            "canonique": self._canonique,
            "canoniques_declares": canoniques,
            "n_orchestrateurs": len(self._enregistres),
        }

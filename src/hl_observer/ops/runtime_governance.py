"""[AUD-202/221] Gouvernance runtime : surveillance de DERIVE d'execution (couts/fills/latence vs
baseline) et REGISTRE UNIFIE des orchestrateurs (un seul point d'entree canonique, pas N pipelines
paralleles qui divergent). stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping

CANONIQUE = "historical_analysis_suite"


def detecter_derive_execution(baseline: Mapping[str, float], courant: Mapping[str, float], *,
                              tolerance: float = 0.20) -> dict:
    """DERIVE d'execution : compare les metriques d'execution (cout, taux de fill, latence) au
    baseline ; signale celles qui derivent de plus de `tolerance` (defaut 20%). Le monde a change ->
    le modele de couts est peut-etre perime."""
    derives = {}
    for k, base in baseline.items():
        cur = float(courant.get(k, base))
        ref = abs(float(base)) if base else 1e-9
        ecart = abs(cur - float(base)) / ref
        if ecart > tolerance:
            derives[k] = {"baseline": float(base), "courant": cur, "ecart_relatif": round(ecart, 4)}
    return {"stable": len(derives) == 0, "derives": derives}


class RegistreOrchestrateurs:
    """Registre UNIFIE des orchestrateurs : un seul est CANONIQUE (point d'entree officiel), les
    autres explicitement secondaires. Empeche N orchestrateurs concurrents qui divergent."""

    def __init__(self, canonique: str = CANONIQUE) -> None:
        self._canonique = canonique
        self._enregistres: dict[str, str] = {}

    def enregistrer(self, nom: str, role: str = "secondaire") -> None:
        self._enregistres[nom] = role

    def canonique(self) -> str:
        return self._canonique

    def verifier_unicite(self) -> dict:
        canoniques = [n for n, r in self._enregistres.items() if r == "canonique"]
        unifie = len(canoniques) == 1 and canoniques[0] == self._canonique
        return {"unifie": unifie, "canonique": self._canonique,
                "canoniques_declares": canoniques, "n_orchestrateurs": len(self._enregistres)}

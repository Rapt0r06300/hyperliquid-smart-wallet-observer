"""[COPY-VAULT lot2 #39] sync_confidence PAR VAULT : un score de confiance de synchronisation par vault, construit à
partir de plusieurs signaux — gaps détectés, accord REST/WS, âge de l'état, réussite de reconstruction de position.
Un score bas signale que ce qu'on croit de ce vault n'est peut-être plus fiable. Score dans [0,1]. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


def score(*, gaps: Any = 0, rest_ws_accord: bool = True, age_etat_ms: Any = 0.0,
          position_reconstruite_ok: bool = True, age_max_ms: float = 30_000.0) -> dict[str, Any]:
    """Combine les signaux en un score [0,1]. Chaque défaut retranche : gaps, désaccord REST/WS, état trop vieux,
    position non reconstructible. Entrées invalides comptent comme défaut (score plus bas, jamais gonflé)."""
    s = 1.0
    penalites = {}
    g = int(gaps) if isinstance(gaps, (int, float)) else 1
    if g > 0:
        p = min(0.5, 0.15 * g)
        s -= p
        penalites["gaps"] = round(p, 4)
    if not bool(rest_ws_accord):
        s -= 0.3
        penalites["rest_ws_desaccord"] = 0.3
    age = float(age_etat_ms) if isinstance(age_etat_ms, (int, float)) else float(age_max_ms) * 2
    if age > float(age_max_ms):
        s -= 0.2
        penalites["etat_trop_vieux"] = 0.2
    if not bool(position_reconstruite_ok):
        s -= 0.3
        penalites["position_non_reconstruite"] = 0.3
    s = max(0.0, min(1.0, s))
    return {"sync_confidence": round(s, 4), "penalites": penalites}


__all__ = ["score"]

"""[COPY-VAULT lot2 #39] sync_confidence PAR VAULT : un score de confiance de synchronisation par vault, construit à
partir de plusieurs signaux — gaps détectés, accord REST/WS, âge de l'état, réussite de reconstruction de position.
Un score bas signale que ce qu'on croit de ce vault n'est peut-être plus fiable. Score dans [0,1]. Pur, 0 réseau.
"""
from __future__ import annotations

import math
from typing import Any


def score(*, gaps: Any = None, rest_ws_accord: bool | None = None, age_etat_ms: Any = None,
          position_reconstruite_ok: bool | None = None, age_max_ms: float = 30_000.0) -> dict[str, Any]:
    """Combine les signaux en un score [0,1]. Chaque défaut retranche : gaps, désaccord REST/WS, état trop vieux,
    position non reconstructible. Toute observation absente ou invalide est non mesurable et refuse l'ouverture."""
    missing = [
        name for name, value in (
            ("gaps", gaps),
            ("rest_ws_accord", rest_ws_accord),
            ("age_etat_ms", age_etat_ms),
            ("position_reconstruite_ok", position_reconstruite_ok),
        ) if value is None
    ]
    try:
        max_age = float(age_max_ms)
    except (TypeError, ValueError):
        max_age = float("nan")
    if not math.isfinite(max_age) or max_age <= 0:
        return {"sync_confidence": None, "state": "UNMEASURABLE", "refuse": True,
                "penalites": {"age_max_invalide": True}}
    if missing:
        return {"sync_confidence": None, "state": "UNMEASURABLE", "refuse": True,
                "penalites": {"observations_absentes": missing}}
    if not isinstance(rest_ws_accord, bool) or not isinstance(position_reconstruite_ok, bool):
        return {"sync_confidence": None, "state": "UNMEASURABLE", "refuse": True,
                "penalites": {"observations_invalides": True}}
    if isinstance(gaps, bool) or not isinstance(gaps, (int, float)) or not math.isfinite(float(gaps)) or gaps < 0:
        return {"sync_confidence": None, "state": "UNMEASURABLE", "refuse": True,
                "penalites": {"gaps_invalides": True}}
    if not isinstance(age_etat_ms, (int, float)) or isinstance(age_etat_ms, bool):
        return {"sync_confidence": None, "state": "UNMEASURABLE", "refuse": True,
                "penalites": {"age_invalide": True}}
    if not math.isfinite(float(age_etat_ms)) or age_etat_ms < 0:
        return {"sync_confidence": None, "state": "UNMEASURABLE", "refuse": True,
                "penalites": {"age_invalide": True}}
    s = 1.0
    penalites = {}
    g = int(gaps)
    if g > 0:
        p = min(0.5, 0.15 * g)
        s -= p
        penalites["gaps"] = round(p, 4)
    if not bool(rest_ws_accord):
        s -= 0.3
        penalites["rest_ws_desaccord"] = 0.3
    age = float(age_etat_ms)
    if age > max_age:
        s -= 0.2
        penalites["etat_trop_vieux"] = 0.2
    if not bool(position_reconstruite_ok):
        s -= 0.3
        penalites["position_non_reconstruite"] = 0.3
    s = max(0.0, min(1.0, s))
    return {"sync_confidence": round(s, 4), "state": "OBSERVED", "refuse": False, "penalites": penalites}


__all__ = ["score"]

"""C1-C5 — Profil de gate strict : durcit le contexte d'entrée (fraîcheur, calibration,
OBI, consensus, régime) quand HYPERSMART_GATE_STRICT_PROFILE est activé. Pur, deny-by-default OFF.
"""

from __future__ import annotations

import os

from hl_observer.signals.regime_router import enabled_strategies

FLAG = "HYPERSMART_GATE_STRICT_PROFILE"


def strict_profile_enabled(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(FLAG, "0")).lower() in ("1", "true", "yes")


def apply_strict_profile(context: dict, *, sigma_bps: float | None = None, env: dict | None = None) -> dict:
    """Renvoie un contexte de gate durci (C1-C5). Sans le flag, retourne le contexte inchangé."""
    if not strict_profile_enabled(env):
        return context
    c = dict(context or {})
    c["min_edge_bps"] = max(float(c.get("min_edge_bps", 30.0)), 30.0)   # C1/C3 sélectivité
    c["require_obi"] = True                                              # C3 OBI obligatoire
    c["min_consensus"] = max(int(c.get("min_consensus", 1)), 2)         # C4 consensus >= 2
    # C2 : le gate refuse déjà si calibrated=False ; on n'assouplit jamais ici.
    # C5 : régime — couper le directionnel en chop/extreme
    if sigma_bps is not None:
        strat = str(c.get("strategy_kind", "copy")).lower()
        allowed = enabled_strategies(float(sigma_bps))
        if strat in ("trend", "direction", "momentum") and strat not in allowed:
            c["conflict"] = True                                        # -> NO_TRADE directionnel
    return c


__all__ = ["FLAG", "strict_profile_enabled", "apply_strict_profile"]

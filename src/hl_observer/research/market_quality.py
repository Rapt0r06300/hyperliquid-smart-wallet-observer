"""[AUD-308/360/361/372] Qualite de marche : regime d'OPTIONS (a partir d'IV/skew), filtre anti-
MANIPULATION (spoofing/wash/quote flicker), detection de PANNES CORRELEES de sources et de
CHANGEMENTS SILENCIEUX d'API (schema). stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence


def classer_regime_options(*, iv_atm: float, skew_25d: float) -> dict:
    """Regime d'options (offline) a partir de l'IV ATM et du skew 25-delta : un skew tres negatif +
    une IV haute = demande de protection = peur (PANIQUE)."""
    if iv_atm >= 0.8 or skew_25d <= -0.10:
        regime = "PANIQUE"
    elif iv_atm >= 0.5 or skew_25d <= -0.05:
        regime = "STRESSE"
    else:
        regime = "CALME"
    return {"regime": regime, "iv_atm": iv_atm, "skew_25d": skew_25d}


def filtrer_manipulation(quotes: Sequence[Mapping], *, flicker_ms: float = 50.0) -> dict:
    """Filtre les quotes MANIPULATOIRES : ordres poses puis retires en < flicker_ms (spoofing/flicker)
    -> ne pas croire un carnet epais qui s'evapore a l'approche."""
    suspects = [i for i, q in enumerate(quotes)
                if q.get("annule_apres_ms") is not None and q["annule_apres_ms"] < flicker_ms]
    sset = set(suspects)
    return {"propres": [q for i, q in enumerate(quotes) if i not in sset],
            "suspects": suspects, "n_suspects": len(suspects)}


def pannes_correlees(status_par_source: Mapping[str, str]) -> dict:
    """Pannes CORRELEES : si plusieurs sources tombent en meme temps, c'est peut-etre NOTRE infra (pas
    les sources) -> ne pas conclure a tort que 'le marche est calme'."""
    down = sorted(n for n, s in status_par_source.items() if s == "DOWN")
    total = len(status_par_source)
    correle = total > 0 and len(down) >= max(2, total // 2)
    return {"panne_correlee": correle, "down": down,
            "cause_probable": "INFRA_LOCALE" if correle else "SOURCE_ISOLEE"}


def detecter_changement_api(schema_avant: Mapping, schema_apres: Mapping) -> dict:
    """Changement SILENCIEUX d'API : champs disparus/apparus/de type change entre deux captures de
    schema -> on ne parse pas a l'aveugle un format qui a bouge."""
    a, b = set(schema_avant), set(schema_apres)
    disparus, apparus = sorted(a - b), sorted(b - a)
    types_changes = sorted(k for k in (a & b) if schema_avant[k] != schema_apres[k])
    return {"a_change": bool(disparus or apparus or types_changes),
            "disparus": disparus, "apparus": apparus, "types_changes": types_changes}

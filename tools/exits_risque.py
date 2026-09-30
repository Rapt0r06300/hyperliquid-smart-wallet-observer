"""EXITS ET RISQUE — stops comme hypothèses, time stop, reduce partiel, MAE/MFE (IDEA-67 → 70).

Un stop n'est pas un réglage : c'est une HYPOTHÈSE qui coûte un essai de plus dans le multiple testing.
Et MAE/MFE servent à COMPRENDRE les sorties, jamais à les optimiser après coup sur les mêmes données.

  • IDEA-67 : familles de stops testées séparément (aucun / fixe / volatilité / temps / flux adverse /
    liquidité / trailing / sortie du leader) — chacune compte comme un essai ;
  • IDEA-68 : time stop — sortir quand rien ne se passe (signal à demi-vie courte) ;
  • IDEA-69 : REDUCE / fermeture partielle, y compris quand la profondeur ne permet pas de tout sortir ;
  • IDEA-70 : MAE (pire excursion adverse) et MFE (meilleure excursion favorable) par position.

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

#: familles de stops (IDEA-67). Chaque famille testée = +1 essai à corriger en multiplicité.
FAMILLES_STOP = ("AUCUN", "FIXE", "VOLATILITE", "TEMPS", "FLUX_ADVERSE", "LIQUIDITE",
                 "TRAILING", "SORTIE_LEADER")


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def plan_experiences_stops(familles=None, *, horizons=None, coins=None) -> dict:
    """IDEA-67 — un stop est une HYPOTHÈSE. Ce plan rend explicite le nombre d'essais que l'on s'apprête à
    consommer : tester 8 familles × 3 horizons × 5 coins = 120 essais, à déclarer en multiple testing."""
    fam = list(familles or FAMILLES_STOP)
    inconnues = [f for f in fam if f not in FAMILLES_STOP]
    if inconnues:
        raise ValueError("famille de stop inconnue: %s" % ",".join(inconnues))
    nh = len(horizons or []) or 1
    nc = len(coins or []) or 1
    return {"familles": fam, "n_familles": len(fam), "n_horizons": nh, "n_coins": nc,
            "n_essais": len(fam) * nh * nc,
            "note": "chaque famille de stop est une hypothese separee (multiple testing)"}


def time_stop(*, ts_entree_ms: float, maintenant_ms: float, duree_max_ms: float,
              mouvement_bps=None, seuil_mouvement_bps: float = 5.0) -> dict:
    """IDEA-68 — sort si la durée maximale PRÉ-ENREGISTRÉE est dépassée sans mouvement significatif.
    Le mouvement inconnu ne vaut pas « pas de mouvement » : il est signalé comme tel."""
    ecoule = float(maintenant_ms) - float(ts_entree_ms)
    if ecoule < float(duree_max_ms):
        return {"sortir": False, "motif": "DUREE_NON_ATTEINTE", "ecoule_ms": round(ecoule, 2)}
    m = _f(mouvement_bps)
    if m is None:
        return {"sortir": True, "motif": "DUREE_DEPASSEE_MOUVEMENT_INCONNU", "ecoule_ms": round(ecoule, 2),
                "avertissement": "mouvement non mesure — sortie par prudence"}
    if abs(m) < float(seuil_mouvement_bps):
        return {"sortir": True, "motif": "AUCUN_MOUVEMENT_APRES_DUREE", "ecoule_ms": round(ecoule, 2),
                "mouvement_bps": m}
    return {"sortir": False, "motif": "MOUVEMENT_SIGNIFICATIF", "mouvement_bps": m}


def reduire_position(*, notional_actuel: float, fraction_demandee: float,
                     profondeur_disponible_usd=None) -> dict:
    """IDEA-69 — REDUCE / fermeture partielle. Si la profondeur ne permet pas de sortir la fraction
    demandée, on sort ce qui est possible et on le DIT (sortie partielle), au lieu de supposer une
    liquidation parfaite."""
    n = _f(notional_actuel) or 0.0
    fr = _f(fraction_demandee)
    if n <= 0 or fr is None or not (0 < fr <= 1):
        return {"statut": "REFUSE", "motif": "NOTIONAL_OU_FRACTION_INVALIDE"}
    voulu = n * fr
    prof = _f(profondeur_disponible_usd)
    reel = voulu if prof is None else min(voulu, max(0.0, prof))
    reste = n - reel
    statut = ("CLOSE" if reste <= 1e-9 else ("REDUCE" if reel > 0 else "NO_FILL"))
    return {"statut": statut, "notional_demande": round(voulu, 6), "notional_reduit": round(reel, 6),
            "fraction_reelle": round(reel / n, 6) if n else None,
            "notional_restant": round(reste, 6),
            "sortie_partielle_faute_de_profondeur": bool(prof is not None and reel < voulu - 1e-9),
            "profondeur_limitante_usd": prof}


def mae_mfe(prix_entree: float, *, sens: int, prix_observes) -> dict:
    """IDEA-70 — MAE (Maximum Adverse Excursion) et MFE (Maximum Favorable Excursion) en bps, mesurées sur
    la trajectoire RÉELLE de la position. Outil d'ANALYSE : s'en servir pour recalibrer un stop sur les
    mêmes données serait du tuning opportuniste (et se paierait en multiple testing)."""
    e = _f(prix_entree)
    xs = [_f(p) for p in (prix_observes or [])]
    xs = [x for x in xs if x is not None and x > 0]
    if e is None or e <= 0 or not xs:
        return {"mesurable": False, "motif": "PRIX_INSUFFISANTS"}
    s = 1 if int(sens) >= 0 else -1
    exc = [s * (x - e) / e * 1e4 for x in xs]
    return {"mesurable": True, "n_points": len(xs),
            "mae_bps": round(min(min(exc), 0.0), 4),          # pire excursion adverse (<= 0)
            "mfe_bps": round(max(max(exc), 0.0), 4),          # meilleure excursion favorable (>= 0)
            "excursion_finale_bps": round(exc[-1], 4),
            "usage": "ANALYSE des sorties — jamais un tuning a posteriori sur les memes donnees"}


def stop_atteint(*, famille: str, mae_bps=None, seuil_bps=None, vol_bps=None, k_vol: float = 2.0,
                 flux_adverse: bool | None = None, leader_sorti: bool | None = None) -> dict:
    """IDEA-67 — évalue UNE famille de stop, sans mélanger les hypothèses. Une donnée manquante rend
    UNMEASURABLE plutôt qu'un « stop non touché » implicite."""
    f = str(famille).upper()
    if f not in FAMILLES_STOP:
        raise ValueError("famille de stop inconnue: %s" % famille)
    if f == "AUCUN":
        return {"stop": False, "famille": f, "motif": "AUCUN_STOP"}
    mae = _f(mae_bps)
    if f == "FIXE":
        s = _f(seuil_bps)
        if mae is None or s is None:
            return {"stop": None, "famille": f, "motif": "UNMEASURABLE"}
        return {"stop": mae <= -abs(s), "famille": f, "seuil_bps": -abs(s), "mae_bps": mae}
    if f == "VOLATILITE":
        v = _f(vol_bps)
        if mae is None or v is None:
            return {"stop": None, "famille": f, "motif": "UNMEASURABLE"}
        seuil = -abs(v) * float(k_vol)
        return {"stop": mae <= seuil, "famille": f, "seuil_bps": round(seuil, 4), "mae_bps": mae}
    if f == "FLUX_ADVERSE":
        return ({"stop": bool(flux_adverse), "famille": f} if flux_adverse is not None
                else {"stop": None, "famille": f, "motif": "UNMEASURABLE"})
    if f == "SORTIE_LEADER":
        return ({"stop": bool(leader_sorti), "famille": f} if leader_sorti is not None
                else {"stop": None, "famille": f, "motif": "UNMEASURABLE"})
    return {"stop": None, "famille": f, "motif": "FAMILLE_NON_EVALUEE_ICI"}


__all__ = ["FAMILLES_STOP", "plan_experiences_stops", "time_stop", "reduire_position", "mae_mfe",
           "stop_atteint"]

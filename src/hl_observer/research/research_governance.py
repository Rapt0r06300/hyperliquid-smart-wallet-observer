"""[AUD-256/257/258/259] Gouvernance de la recherche : dedup ECONOMIQUE des clones (ne pas compter
N strategies identiques comme N essais), rapport comparant les ORCHESTRATEURS, garde 'mode MAXIMUM'
(un optimiseur absent est SIGNALE, jamais ignore en silence) et preuve de RESULTAT IDENTIQUE apres
unification. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

import json
from typing import Mapping, Sequence


def dedup_clones_economiques(strategies: Sequence[Mapping], *, cle: str = "signature_economique") -> dict:
    """Dedup ECONOMIQUE : deux strategies de meme signature economique = UN seul essai (sinon N clones
    gonflent artificiellement le compte du multiple-testing et faussent la correction)."""
    vus: dict = {}
    uniques, doublons = [], []
    for s in strategies:
        k = s.get(cle)
        if k in vus:
            doublons.append(s)
        else:
            vus[k] = s
            uniques.append(s)
    return {"uniques": uniques, "n_uniques": len(uniques),
            "n_doublons": len(doublons), "doublons": doublons}


def comparer_orchestrateurs(resultats_par_orchestrateur: Mapping[str, object]) -> dict:
    """Rapport comparant les sorties de N orchestrateurs : signale toute DIVERGENCE (deux orchestrateurs
    censes faire la meme chose doivent rendre le meme resultat)."""
    reps = {nom: json.dumps(r, sort_keys=True, default=str) for nom, r in resultats_par_orchestrateur.items()}
    distinctes = set(reps.values())
    ref = min(reps.values()) if reps else None
    divergents = sorted(nom for nom, rep in reps.items() if rep != ref) if len(distinctes) > 1 else []
    return {"identiques": len(distinctes) <= 1, "n": len(reps), "divergents": divergents}


def garde_optimiseurs_max(optimiseurs_requis: Sequence[str], optimiseurs_disponibles: Sequence[str]) -> dict:
    """Mode MAXIMUM : si un optimiseur requis est ABSENT, on le SIGNALE (le mode 'max' ne doit jamais
    sauter un optimiseur en silence et se croire exhaustif)."""
    dispo = set(optimiseurs_disponibles)
    manquants = [o for o in optimiseurs_requis if o not in dispo]
    return {"complet": len(manquants) == 0, "manquants": manquants}


def resultat_identique_apres_unification(avant, apres, *, tolerance: float = 1e-9) -> dict:
    """Preuve que l'UNIFICATION (fusion de chemins/moteurs) donne EXACTEMENT le meme resultat qu'avant
    -> une refonte ne doit pas changer les chiffres en douce."""
    if isinstance(avant, (int, float)) and isinstance(apres, (int, float)):
        identique = abs(float(avant) - float(apres)) <= tolerance
    else:
        identique = (json.dumps(avant, sort_keys=True, default=str)
                     == json.dumps(apres, sort_keys=True, default=str))
    return {"identique": identique}

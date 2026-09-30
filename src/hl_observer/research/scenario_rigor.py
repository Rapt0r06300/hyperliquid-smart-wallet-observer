"""[AUD-167/169/170/171/172/174/179] Rigueur des scenarios : couverture MESUREE, ablations
systematiques, contrefactuels systematiques (facteurs on/off), clustering des erreurs, test de
TRANSFERT (train A -> test B : coin/venue/regime), marche AGENT-BASED synthetique (etiquete
SYNTHETIQUE) et rapport 'maximum de pistes'. Deterministe (seed), stdlib pure, 0 reseau."""
from __future__ import annotations

import random
from itertools import product
from typing import Callable, Mapping, Sequence


def couverture_scenarios(requis: Sequence[str], couverts: Sequence[str]) -> dict:
    """Couverture de scenarios MESUREE : quels scenarios requis sont effectivement couverts ?"""
    req = list(dict.fromkeys(requis))
    cset = set(couverts)
    manquants = [s for s in req if s not in cset]
    taux = (len(req) - len(manquants)) / len(req) if req else 1.0
    return {"taux": taux, "manquants": manquants, "n_requis": len(req)}


def ablation_sweep(composants: Sequence[str], evaluer_sans: Callable[[frozenset], float]) -> list[dict]:
    """Ablation SYSTEMATIQUE : retire chaque composant un a un, mesure la chute -> importance.
    `evaluer_sans(retires)` rend la perf quand l'ensemble `retires` est absent."""
    ref = float(evaluer_sans(frozenset()))
    out = [{"composant": c, "perf_sans": float(evaluer_sans(frozenset([c])))} for c in composants]
    for d in out:
        d["delta"] = ref - d["perf_sans"]
    out.sort(key=lambda d: d["delta"], reverse=True)
    return out


def contrefactuels_systematiques(facteurs: Sequence[str], evaluer: Callable[[dict], float]) -> list[dict]:
    """Contrefactuels SYSTEMATIQUES : bascule chaque facteur ON/OFF (plan complet 2^k borne) et
    mesure l'effet marginal moyen de chaque facteur."""
    facteurs = list(facteurs)
    if len(facteurs) > 12:
        raise ValueError("trop de facteurs pour un plan complet (<=12)")
    combos = list(product([False, True], repeat=len(facteurs)))
    perf = {c: float(evaluer(dict(zip(facteurs, c)))) for c in combos}
    effets = []
    for i, f in enumerate(facteurs):
        diff, n = 0.0, 0
        for c in combos:
            if not c[i]:
                c_on = tuple(True if j == i else c[j] for j in range(len(facteurs)))
                diff += perf[c_on] - perf[c]
                n += 1
        effets.append({"facteur": f, "effet_marginal_moyen": diff / n if n else 0.0})
    effets.sort(key=lambda d: abs(d["effet_marginal_moyen"]), reverse=True)
    return effets


def clusterer_erreurs(erreurs: Sequence[Mapping], *, cle: str = "signature") -> list[dict]:
    """Clustering des erreurs par SIGNATURE : regroupe les erreurs identiques -> priorise les
    familles les plus frequentes plutot que traiter N erreurs isolees."""
    groupes: dict = {}
    for e in erreurs:
        groupes.setdefault(e.get(cle, "INCONNU"), []).append(e)
    clusters = [{"signature": k, "n": len(v), "exemples": v[:3]} for k, v in groupes.items()]
    clusters.sort(key=lambda d: d["n"], reverse=True)
    return clusters


def evaluer_transfert(perf_par_groupe: Mapping[str, float], *, seuil: float = 0.0) -> dict:
    """Test de TRANSFERT / generalisation hors-groupe : pour chaque groupe (coin/venue/regime), la
    perf reste-t-elle > seuil ? Un edge qui ne transfere pas = sur-ajustement."""
    detail = {g: (float(p) > seuil) for g, p in perf_par_groupe.items()}
    echecs = [g for g, ok in detail.items() if not ok]
    return {"transfere_partout": len(echecs) == 0, "echecs": echecs, "detail": detail,
            "taux_transfert": (len(detail) - len(echecs)) / len(detail) if detail else 1.0}


def simuler_marche_agent_based(n_pas: int, *, n_agents: int = 10, seed: int = 7) -> dict:
    """Marche AGENT-BASED synthetique : des agents bruites poussent un prix (marche aleatoire borne).
    ETIQUETE SYNTHETIQUE -> jamais confondu avec du reel. Deterministe (seed)."""
    rng = random.Random(seed)
    prix = 100.0
    serie = [prix]
    for _ in range(n_pas):
        flux = sum(rng.choice([-1, 1]) for _ in range(n_agents))
        prix = max(0.01, prix + 0.01 * flux)
        serie.append(round(prix, 4))
    return {"data_origin": "SYNTHETIQUE", "real_execution": False, "prix": serie, "n_pas": n_pas}


def rapport_maximum_pistes(pistes: Sequence[Mapping], *, cle_score: str = "score") -> dict:
    """Rapport 'MAXIMUM de pistes' : liste TOUTES les pistes explorees (pas seulement la gagnante),
    triees par score -> tracabilite complete de l'espace couvert."""
    triees = sorted(pistes, key=lambda p: float(p.get(cle_score, 0.0)), reverse=True)
    return {"n_pistes": len(triees), "pistes": list(triees), "meilleure": triees[0] if triees else None}

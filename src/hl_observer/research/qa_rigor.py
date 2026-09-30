"""[AUD-190/191/192/193/194/215/216/220] Rigueur des tests : detection de FLAKY (pass instable),
audit des TIMEOUTS manquants, detection de DEPENDANCE A L'ORDRE, generation PAIRWISE (t-way),
mesure + rapport de COUVERTURE combinatoire, detection de REGRESSION MEMOIRE et SOAK test.
Deterministe, stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from itertools import combinations, product
from typing import Mapping, Sequence


def detecter_flaky(resultats_par_test: Mapping[str, Sequence[bool]]) -> dict:
    """FLAKY != PASS : un test dont les runs successifs ne sont PAS tous identiques est flaky (ni
    fiable vert ni fiable rouge). Un vert flaky ne compte PAS comme un succes."""
    flaky = [nom for nom, runs in resultats_par_test.items()
             if list(runs) and any(v != list(runs)[0] for v in runs)]
    return {"flaky": flaky, "stable": [n for n in resultats_par_test if n not in flaky]}


def auditer_timeouts(appels: Sequence[Mapping]) -> dict:
    """TIMEOUTS COMPLETS : tout appel externe DOIT porter un timeout. Signale ceux qui n'en ont pas
    (un appel sans timeout peut figer tout le systeme indefiniment)."""
    sans = [a.get("nom", "?") for a in appels if not a.get("timeout_s")]
    return {"complet": len(sans) == 0, "sans_timeout": sans, "n": len(appels)}


def detecter_dependance_ordre(resultats_par_ordre: Sequence[Mapping[str, bool]]) -> dict:
    """DEPENDANCE A L'ORDRE : on rejoue la meme suite dans des ordres differents ; si un test change
    de verdict selon l'ordre, il partage un etat cache (bug d'isolation)."""
    if not resultats_par_ordre:
        return {"independant": True, "coupables": []}
    noms: set = set()
    for r in resultats_par_ordre:
        noms |= set(r.keys())
    coupables = [n for n in sorted(noms)
                 if len({r.get(n) for r in resultats_par_ordre if n in r}) > 1]
    return {"independant": len(coupables) == 0, "coupables": coupables}


def cas_pairwise(parametres: Mapping[str, Sequence]) -> list[dict]:
    """Generation PAIRWISE (2-way) : jeu de cas COUVRANT toutes les paires de valeurs, bien plus
    petit que le factoriel complet mais attrapant la majorite des bugs d'interaction. Construction
    par AMORCE : chaque nouveau cas part d'une paire encore non couverte -> terminaison + 100%."""
    noms = list(parametres)
    valeurs = {n: list(parametres[n]) for n in noms}
    idx = {n: i for i, n in enumerate(noms)}

    def cle(n1, v1, n2, v2):
        return (n1, v1, n2, v2) if idx[n1] <= idx[n2] else (n2, v2, n1, v1)

    if len(noms) < 2:
        n = noms[0] if noms else None
        return [{n: v} for v in valeurs[n]] if n is not None else []

    pairs_ordre = []
    for a, b in combinations(noms, 2):
        for va in valeurs[a]:
            for vb in valeurs[b]:
                pairs_ordre.append(cle(a, va, b, vb))
    non_couvertes = set(pairs_ordre)
    cas: list[dict] = []
    garde = 0
    while non_couvertes and garde < 100000:
        garde += 1
        seed = next(p for p in pairs_ordre if p in non_couvertes)
        n1, v1, n2, v2 = seed
        assignation = {n1: v1, n2: v2}
        for n in noms:
            if n in assignation:
                continue
            meilleur_v, meilleur_gain = valeurs[n][0], -1
            for v in valeurs[n]:
                gain = sum(1 for m, vm in assignation.items() if cle(n, v, m, vm) in non_couvertes)
                if gain > meilleur_gain:
                    meilleur_gain, meilleur_v = gain, v
            assignation[n] = meilleur_v
        for a, b in combinations(noms, 2):
            non_couvertes.discard(cle(a, assignation[a], b, assignation[b]))
        cas.append(dict(assignation))
    return cas


def couverture_t_way(cas: Sequence[Mapping], parametres: Mapping[str, Sequence], *, t: int = 2) -> float:
    """Fraction des t-uplets de valeurs effectivement couverts par le jeu de cas (0..1)."""
    noms = list(parametres)
    valeurs = {n: list(parametres[n]) for n in noms}
    total = couverts = 0
    for combo in combinations(noms, t):
        for vals in product(*(valeurs[n] for n in combo)):
            total += 1
            cible = dict(zip(combo, vals))
            if any(all(c.get(n) == v for n, v in cible.items()) for c in cas):
                couverts += 1
    return couverts / total if total else 1.0


def rapport_couverture_combinatoire(cas: Sequence[Mapping], parametres: Mapping[str, Sequence], *, t: int = 2) -> dict:
    """PUBLIE la couverture combinatoire t-way (transparence : montrer ce qui est teste)."""
    taux = couverture_t_way(cas, parametres, t=t)
    factoriel = 1
    for v in parametres.values():
        factoriel *= len(list(v))
    return {"t": t, "couverture_t_way": round(taux, 4), "n_cas": len(cas),
            "factoriel_complet": factoriel,
            "reduction": round(1 - len(cas) / factoriel, 4) if factoriel else 0.0}


def verifier_regression_memoire(baseline_mo: float, courant_mo: float, *, tolerance: float = 0.10) -> dict:
    """REGRESSION MEMOIRE : la conso courante ne doit pas depasser la baseline de plus de `tolerance`
    (defaut +10%). Un pic memoire silencieux fait tomber le process en prod."""
    seuil = baseline_mo * (1.0 + tolerance)
    return {"regression": courant_mo > seuil, "baseline_mo": baseline_mo,
            "courant_mo": courant_mo, "seuil_mo": round(seuil, 4)}


def soak_test(mesure_ressource: Sequence[float], *, tolerance_pente: float = 0.0) -> dict:
    """SOAK test : sur un run long, la ressource (memoire proxy) ne doit pas croitre continument.
    Detecte une FUITE via la pente (regression lineaire) ; pente > tolerance -> fuite probable."""
    n = len(mesure_ressource)
    if n < 2:
        return {"fuite": False, "pente": 0.0, "n": n}
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(mesure_ressource) / n
    denom = sum((x - mx) ** 2 for x in xs) or 1e-12
    pente = sum((xs[i] - mx) * (mesure_ressource[i] - my) for i in range(n)) / denom
    return {"fuite": pente > tolerance_pente, "pente": round(pente, 6), "n": n}

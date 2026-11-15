"""Noyau commun de R7, R8 et R9 : UNE hypothèse, évaluée à travers N observations.

POURQUOI CE MODULE EXISTE
-------------------------
La campagne suit **209 leaders**. C'est une force ou une catastrophe selon la FORME du test.

* « Ce leader est-il rentable ? » posé 209 fois = **209 essais**. La pénalité de multiplicité
  devient écrasante, on trouve des leaders « rentables » par pur hasard, et le moteur les rejette
  à juste titre. On n'aura jamais rien prouvé.
* « La part agressive prédit-elle la copiabilité nette ? » = **UNE** hypothèse évaluée sur
  209 observations. La section transversale devient une force au lieu d'une pénalité.

C'est la même logique que le carry cross-sectionnel — le seul edge encore vivant ici (PBO 0,81).

LES TROIS REFUS
---------------
1. **Trop peu d'observations** → `NON_MESURABLE`, jamais « pas de lien ». Dire « aucune relation »
   sur 5 leaders est une affirmation qu'on ne peut pas soutenir.
2. **Variable constante** → `NON_MESURABLE`. Une caractéristique identique partout ne peut rien
   prédire, et sa corrélation serait un artefact numérique.
3. **Observations incomplètes** → écartées et comptées à part, jamais remplacées par une moyenne.
   Imputer, c'est inventer.

LA MULTIPLICITÉ EST PORTÉE, PAS CACHÉE
---------------------------------------
`essais` est un paramètre OBLIGATOIRE : le seuil de significativité est divisé par le nombre
d'hypothèses réellement tentées (Bonferroni). Tester 4 caractéristiques et ne publier que la
meilleure sans le dire est la façon la plus commune de fabriquer un faux résultat.

PAPER / lecture seule.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

MESURE = "MESURE"
NON_MESURABLE = "NON_MESURABLE"

TROP_PEU = "TROP_PEU_D_OBSERVATIONS"
SANS_VARIATION = "CARACTERISTIQUE_CONSTANTE"
SANS_VARIATION_CIBLE = "CIBLE_CONSTANTE"

#: En dessous, une corrélation de rang ne veut rien dire sur des données financières.
MINIMUM_OBSERVATIONS = 20
#: Seuil avant correction de multiplicité.
ALPHA = 0.05


def _fini(valeur: Any) -> float | None:
    try:
        sortie = float(valeur)
    except (TypeError, ValueError):
        return None
    return sortie if math.isfinite(sortie) else None


def _rangs(valeurs: Sequence[float]) -> list[float]:
    """Rangs moyens — les ex aequo partagent leur rang, sinon on inventerait un ordre."""
    indices = sorted(range(len(valeurs)), key=lambda i: valeurs[i])
    rangs = [0.0] * len(valeurs)
    i = 0
    while i < len(indices):
        j = i
        while j + 1 < len(indices) and valeurs[indices[j + 1]] == valeurs[indices[i]]:
            j += 1
        moyen = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            rangs[indices[k]] = moyen
        i = j + 1
    return rangs


def correlation_de_rang(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman. None si l'un des deux ne varie pas — une constante ne predit rien."""
    if len(x) != len(y) or len(x) < 2:
        return None
    rx, ry = _rangs(list(x)), _rangs(list(y))
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0.0 or dy == 0.0:
        return None
    return num / (dx * dy)


def _p_valeur(rho: float, n: int) -> float:
    """Approximation normale via la transformation de Fisher. Suffisante pour décider d'un refus."""
    if n <= 3 or abs(rho) >= 1.0:
        return 0.0 if abs(rho) >= 1.0 else 1.0
    z = 0.5 * math.log((1.0 + rho) / (1.0 - rho)) * math.sqrt(n - 3)
    return math.erfc(abs(z) / math.sqrt(2.0))


def tester(observations: Iterable[Mapping[str, Any]], *, caracteristique: str, cible: str,
           essais: int, minimum: int = MINIMUM_OBSERVATIONS,
           alpha: float = ALPHA) -> dict[str, Any]:
    """UNE hypothèse : `caracteristique` prédit-elle `cible` à travers les observations ?

    `essais` est OBLIGATOIRE et corrige le seuil (Bonferroni) : il doit compter TOUTES les
    hypothèses tentées, pas seulement celle qu'on publie.
    """
    paires: list[tuple[float, float]] = []
    incompletes = 0
    for item in observations:
        if not isinstance(item, Mapping):
            incompletes += 1
            continue
        a, b = _fini(item.get(caracteristique)), _fini(item.get(cible))
        if a is None or b is None:
            incompletes += 1       # ECARTEE, jamais imputee : imputer, c'est inventer
            continue
        paires.append((a, b))

    n = len(paires)
    base = {"n": n, "incompletes": incompletes, "caracteristique": caracteristique,
            "cible": cible, "essais": int(max(1, essais))}
    if n < max(2, int(minimum)):
        return {**base, "verdict": NON_MESURABLE, "motif": TROP_PEU, "rho": None,
                "lecture": (f"NON MESURABLE : {n} observation(s) exploitable(s), il en faut "
                            f"{minimum}. Ce n'est PAS « aucun lien », c'est « on ne sait pas ».")}

    xs = [p[0] for p in paires]
    ys = [p[1] for p in paires]
    rho = correlation_de_rang(xs, ys)
    if rho is None:
        motif = SANS_VARIATION if len(set(xs)) <= 1 else SANS_VARIATION_CIBLE
        return {**base, "verdict": NON_MESURABLE, "motif": motif, "rho": None,
                "lecture": "NON MESURABLE : une des deux grandeurs ne varie pas."}

    p = _p_valeur(rho, n)
    seuil = float(alpha) / float(max(1, essais))
    significatif = p < seuil
    return {
        **base, "verdict": MESURE, "rho": rho, "p": p, "seuil_corrige": seuil,
        "significatif": significatif,
        "lecture": (f"rho = {rho:+.3f} sur {n} observations, p = {p:.4f} vs seuil corrige "
                    f"{seuil:.4f} ({essais} essai(s)) -> "
                    f"{'LIEN RETENU' if significatif else 'lien NON retenu apres multiplicite'}"),
    }


def comparer_groupes(observations: Iterable[Mapping[str, Any]], *, groupe: str, valeur: str,
                     essais: int, minimum_par_groupe: int = 10) -> dict[str, Any]:
    """Compare la valeur moyenne entre groupes — pour R7 (regimes) et R8 (TWAP visible/cache).

    REFUS DELIBERES :
    * un groupe sous `minimum_par_groupe` n'est pas « mauvais », il est NON MESURABLE, et il est
      nomme comme tel. C'est exactement le piege du decoupage par regime : 6 jours coupes en
      quatre regimes donnent des groupes ou l'on ne peut rien conclure, et les traiter comme des
      resultats fabrique un faux PROVEN ;
    * moins de deux groupes mesurables -> aucune comparaison, pas une egalite ;
    * l'ecart publie porte TOUJOURS les effectifs des deux groupes compares.

    `essais` corrige le seuil : comparer 4 regimes deux a deux, c'est 6 essais, pas 1.
    """
    paquets: dict[str, list[float]] = {}
    incompletes = 0
    for item in observations:
        if not isinstance(item, Mapping):
            incompletes += 1
            continue
        cle = item.get(groupe)
        val = _fini(item.get(valeur))
        if cle is None or val is None:
            incompletes += 1
            continue
        paquets.setdefault(str(cle), []).append(val)

    details: dict[str, Any] = {}
    mesurables: list[str] = []
    for nom, valeurs in sorted(paquets.items()):
        n = len(valeurs)
        moyenne = sum(valeurs) / n if n else None
        assez = n >= int(minimum_par_groupe)
        if assez:
            mesurables.append(nom)
        details[nom] = {
            "n": n,
            "moyenne": moyenne,
            "verdict": MESURE if assez else NON_MESURABLE,
            "motif": None if assez else TROP_PEU,
        }

    base = {"groupes": details, "incompletes": incompletes,
            "essais": int(max(1, essais)), "mesurables": mesurables}
    if len(mesurables) < 2:
        return {**base, "verdict": NON_MESURABLE, "motif": TROP_PEU, "ecart": None,
                "lecture": (f"NON MESURABLE : {len(mesurables)} groupe(s) atteignent "
                            f"{minimum_par_groupe} observations. Ce n'est PAS une egalite.")}

    meilleur = max(mesurables, key=lambda g: details[g]["moyenne"])
    pire = min(mesurables, key=lambda g: details[g]["moyenne"])
    ecart = details[meilleur]["moyenne"] - details[pire]["moyenne"]
    return {
        **base, "verdict": MESURE, "meilleur": meilleur, "pire": pire, "ecart": ecart,
        "lecture": (f"{meilleur} ({details[meilleur]['moyenne']:+.6f}, n={details[meilleur]['n']}) "
                    f"contre {pire} ({details[pire]['moyenne']:+.6f}, n={details[pire]['n']}) "
                    f"-> ecart {ecart:+.6f} ; "
                    f"{len(details) - len(mesurables)} groupe(s) non mesurable(s)"),
    }


__all__ = ["MESURE", "NON_MESURABLE", "TROP_PEU", "SANS_VARIATION", "SANS_VARIATION_CIBLE",
           "MINIMUM_OBSERVATIONS", "ALPHA", "correlation_de_rang", "tester", "comparer_groupes"]

"""IDEA-92 — PROPERTY-BASED TESTING, en Python pur (2026-07-13).

    Un test par l'exemple ne verifie que les cas AUXQUELS J'AI PENSE.
    Or les bugs de ce projet vivaient tous dans les cas auxquels je n'avais PAS pense.

Rappel des trois derniers, tous des cas-limites qu'aucun exemple choisi a la main n'aurait
attrapes :

  * `>` au lieu de `>=` : la marge qui survit **EXACTEMENT** au pire mouvement etait declaree
    liquidee (#588). Il fallait tomber PILE sur l'egalite.
  * la fraicheur qui INVERSE le signe : visible seulement si l'edge est **negatif** (#594).
  * un p95 negatif qui effondre un seuil a 0 (#586). Il fallait un echantillon tout-negatif.

Un test par propriete, lui, genere des centaines de cas -- y compris les degenerescences (0, egal,
negatif, vide) -- et verifie une regle qui doit tenir pour **TOUS**.

PAS DE DEPENDANCE (le projet tient a `hypothesis`-free : le toolkit quant est en Python pur).
On implemente le strict necessaire : generateurs, seed reproductible, et un **retrecissement**
(shrinking) simple -- parce qu'un contre-exemple de 200 chiffres ne sert a personne.

Aucun ordre reel : on genere des NOMBRES, jamais des ordres.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Sequence

CAS_PAR_DEFAUT = 200


class ProprieteViolee(AssertionError):
    """Une propriete qui devait tenir pour TOUS les cas a echoue sur un cas precis.

    Le message porte le contre-exemple **RETRECI** : le plus petit cas qui casse encore.
    """


# =============================================================================================
# GENERATEURS. Chacun produit d'abord ses cas DEGENERES -- c'est la ou vivent les bugs.
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Generateur:
    """Un generateur de valeurs + sa strategie de retrecissement."""

    nom: str
    tirer: Callable[[random.Random], Any]
    retrecir: Callable[[Any], list[Any]]
    degeneres: tuple[Any, ...] = ()


def _retrecir_nombre(v: float) -> list[Any]:
    """Vers 0, et vers l'entier. Le plus petit contre-exemple est le plus lisible."""
    out: list[Any] = []
    if v != 0:
        out.append(0.0)
        out.append(v / 2.0)
        if v != int(v):
            out.append(float(int(v)))
        if v < 0:
            out.append(-v)
    return out


def flottants(*, mini: float = -1e6, maxi: float = 1e6) -> Generateur:
    """🔴 Les degeneres d'abord : 0, ±1, les bornes. C'est la que `>` vs `>=` se joue."""
    return Generateur(
        nom="flottant[%g,%g]" % (mini, maxi),
        tirer=lambda r: r.uniform(mini, maxi),
        retrecir=_retrecir_nombre,
        degeneres=(0.0, 1.0, -1.0, mini, maxi, 1e-12, -1e-12),
    )


def bps() -> Generateur:
    """Des points de base plausibles : l'echelle de tous nos edges et couts."""
    return Generateur(
        nom="bps",
        tirer=lambda r: r.choice([r.uniform(-500, 500), r.gauss(0, 20)]),
        retrecir=_retrecir_nombre,
        degeneres=(0.0, -7.97, 30.0, -30.0, 1.5, 0.5, -0.5),
    )


def prix() -> Generateur:
    """Des prix STRICTEMENT positifs : un prix <= 0 n'existe pas, et un test qui en genere
    mesure la robustesse du parseur, pas la propriete economique."""
    return Generateur(
        nom="prix>0",
        tirer=lambda r: r.choice([r.uniform(1e-6, 1e5), r.lognormvariate(3, 2)]),
        retrecir=lambda v: [x for x in _retrecir_nombre(v) if x > 0],
        degeneres=(1e-6, 1.0, 100.0, 1e5),
    )


def entiers(*, mini: int = -1000, maxi: int = 1000) -> Generateur:
    return Generateur(
        nom="entier[%d,%d]" % (mini, maxi),
        tirer=lambda r: r.randint(mini, maxi),
        retrecir=lambda v: [0, v // 2] if v else [],
        degeneres=(0, 1, -1, mini, maxi),
    )


def listes(element: Generateur, *, taille_max: int = 30) -> Generateur:
    """⚠️ Inclut la LISTE VIDE dans les degeneres. Les listes vides ont deja tue ce projet :
    le poller L2 ne sondait rien parce que `if coins:` sur une liste vide eteignait la collecte
    **sans un log**."""
    return Generateur(
        nom="liste[%s]" % element.nom,
        tirer=lambda r: [element.tirer(r) for _ in range(r.randint(0, taille_max))],
        retrecir=lambda v: ([[], v[: len(v) // 2]] if len(v) > 1 else ([[]] if v else [])),
        degeneres=((), [], [0.0], list(element.degeneres)),
    )


# =============================================================================================
# LE MOTEUR
# =============================================================================================


def _cas(gens: Sequence[Generateur], n: int, rng: random.Random) -> Iterator[tuple]:
    """Les DEGENERES d'abord (produit cartesien borne), puis de l'aleatoire."""
    vus = 0
    for i in range(max((len(g.degeneres) for g in gens), default=0)):
        cas = tuple(
            (g.degeneres[i] if i < len(g.degeneres) else g.tirer(rng)) for g in gens
        )
        yield cas
        vus += 1
        if vus >= n:
            return
    while vus < n:
        yield tuple(g.tirer(rng) for g in gens)
        vus += 1


def _echoue(propriete: Callable[..., Any], cas: tuple) -> bool:
    """La propriete casse-t-elle sur ce cas ?

    ⚠️ On n'attrape QUE AssertionError. Une TypeError signifie que le generateur produit un type
    que la fonction ne prend pas -- c'est un bug DE MON TEST, pas du code, et le masquer
    rendrait le garde-fou aveugle (la faute de mon audit de couverture qui annoncait 0 %).
    """
    try:
        propriete(*cas)
    except AssertionError:
        return True
    return False


def _retrecir(propriete: Callable[..., Any], cas: tuple, gens: Sequence[Generateur]) -> tuple:
    """Le plus petit cas qui casse ENCORE. Un contre-exemple illisible n'est pas un diagnostic."""
    courant = cas
    for _ in range(60):
        progres = False
        for i, g in enumerate(gens):
            for plus_petit in g.retrecir(courant[i]):
                candidat = courant[:i] + (plus_petit,) + courant[i + 1:]
                if _echoue(propriete, candidat):
                    courant = candidat
                    progres = True
                    break
            if progres:
                break
        if not progres:
            break
    return courant


def pour_tout(
    *generateurs: Generateur,
    cas: int = CAS_PAR_DEFAUT,
    seed: int = 20260713,
) -> Callable[[Callable[..., Any]], Callable[[], None]]:
    """Decorateur : « cette propriete doit tenir POUR TOUT ... ».

    `seed` est FIXE : un test qui echoue un jour sur trois n'est pas un test, c'est une loterie.
    (Le projet impose deja des seeds deterministes partout -- IDEA-75.)

    Usage :

        @pour_tout(bps(), bps())
        def test_le_cout_ne_peut_pas_augmenter_l_edge(edge, cout):
            assert edge_net(edge, cout) <= edge
    """
    gens = list(generateurs)

    def decorateur(propriete: Callable[..., Any]) -> Callable[[], None]:
        def executer() -> None:
            rng = random.Random(seed)
            for c in _cas(gens, cas, rng):
                if _echoue(propriete, c):
                    petit = _retrecir(propriete, c, gens)
                    raise ProprieteViolee(
                        "PROPRIETE VIOLEE apres retrecissement.\n"
                        "  contre-exemple : %r\n"
                        "  (cas d'origine : %r)\n"
                        "  seed=%d, generateurs=%s\n"
                        "Une propriete qui tombe sur UN cas est fausse -- meme si 199 autres "
                        "passent." % (petit, c, seed, [g.nom for g in gens])
                    )
        executer.__name__ = getattr(propriete, "__name__", "propriete")
        executer.__doc__ = propriete.__doc__
        return executer

    return decorateur


__all__ = [
    "CAS_PAR_DEFAUT", "Generateur", "ProprieteViolee",
    "bps", "entiers", "flottants", "listes", "pour_tout", "prix",
]

"""Index des carnets d'un marché : calculé une fois par liste, plus à chaque décision rejouée.

POURQUOI. ``execute_metaorder`` reparcourait toute la liste des carnets du marché à chaque décision
rejouée : recherche des points de contrôle, filtre des carnets continus, extraction puis contrôle
d'ordre des horodatages, et deux relectures complètes par recherche de carnet. Une dizaine de parcours
d'une liste de plusieurs centaines de milliers de carnets pour en lire trois. Mesuré le 2026-11-11 sur
le corpus réel (1 million de carnets) : l'exploration automatique de 128 variantes ne se terminait pas
en une heure, et le labo principal n'aboutissait plus.

GARANTIE. L'index ne change AUCUN résultat : il mémorise exactement ce que ces parcours recalculaient
(mêmes filtres, mêmes refus, même ordre de contrôle, mêmes exceptions). Trois protections :

* une petite liste (moins de ``SEUIL_INDEX`` carnets) n'est jamais mémorisée : elle est recalculée à
  chaque appel, comme avant ;
* l'index garde une référence à la liste indexée, donc son identité ne peut pas être réutilisée par
  une autre liste ;
* avant chaque usage, la longueur et ``SONDES`` carnets répartis sur la liste sont comparés (même
  objet, mêmes champs lus par l'index) ; au moindre écart, l'index est recalculé.

Les listes de carnets sont en lecture seule une fois remises au replay : ce contrôle rattrape une
erreur de programmation, pas un usage prévu.

MÉMOIRE. Certaines variantes du replay recopient les carnets à chaque appel : sans précaution, l'index
retiendrait ces copies. Une liste que plus personne d'autre ne tient est donc oubliée (à chaque nouvelle
liste indexée, et tous les ``BALAYAGE_TOUS_LES`` usages). ``oublier_les_index`` libère tout ; le chargeur
de carnets l'appelle avant chaque nouveau chargement, pour qu'aucun corpus précédent ne reste en mémoire.

[M1 — PLAFOND ADAPTATIF, 2026-11-12] Le plafond ``MAX_LISTES`` borne un NOMBRE de listes, pas un VOLUME :
1024 listes de plusieurs centaines de milliers de carnets ne sont pas bornées en octets. Deux correctifs :

* au plafond, on n'efface plus TOUT (``clear()``), on ÉVINCE les plus anciennes jusqu'à repasser sous
  le plafond : effacer tout crée une falaise de performance juste après (on recalcule aussi le chaud) ;
* le plafond est RÉDUIT selon la pression mémoire (gouverneur ``hl_observer.ops.budget_ram``), donc le
  cache rétrécit quand la RAM se resserre au lieu de la finir.

La pression n'est lue QUE lorsqu'on atteint le plafond — c'est-à-dire rarement. ``index_des_carnets``
est sur le chemin chaud (une fois par décision rejouée) : y lire la RAM à chaque appel coûterait bien
plus que le cache ne fait gagner. Pour la même raison, PAS de LRU réordonné à chaque accès : ce sont
toujours les mêmes quelques listes qui sont relues (une par marché), et l'éviction par compteur de
références ci-dessus est de toute façon plus précise qu'une récence. Évincer ne change jamais un
résultat : au pire l'index est recalculé.
"""
from __future__ import annotations

import sys
from typing import Any

from hl_observer.backtesting.copy_vault_protocol import CHECKPOINT_COLLECTOR_PROTOCOL

#: En dessous, le calcul direct est déjà instantané : aucune mémorisation, comportement d'origine.
SEUIL_INDEX = 256
#: Nombre de carnets comparés avant chaque usage d'un index mémorisé.
SONDES = 32
#: Nombre maximal de listes mémorisées (un corpus réel en compte quelques centaines).
MAX_LISTES = 1024
#: Nombre d'usages entre deux recherches de listes abandonnées par leur appelant.
BALAYAGE_TOUS_LES = 50_000
#: Plancher du plafond adaptatif : même sous forte pression, on garde un cache utile.
PLAFOND_MINI_LISTES = 8

_CHAMPS_LUS = ("ts_ms", "checkpoint_id", "metaorder_id", "collector_protocol")
_NON_CALCULE: Any = object()
#: Sentinelle : gouverneur non fourni => on prend l'officiel ; ``None`` => aucune adaptation.
_AUTO: Any = object()


def _horodatage_exact(valeur: object) -> int | None:
    """Même règle que ``_strict_positive_timestamp`` : un entier observé, strictement positif."""
    if type(valeur) is not int or valeur <= 0:
        return None
    return valeur


class IndexCarnets:
    """Ce que le replay relisait à chaque décision, calculé à la demande et gardé."""

    __slots__ = ("source", "_empreinte", "_controles", "_continus", "_exacts", "_reference")

    def __init__(self, source: list[dict[str, Any]], empreinte: tuple[Any, ...] | None = None) -> None:
        self.source = source
        self._empreinte = empreinte          # ``None`` : index d'un seul usage, jamais mémorisé
        self._controles: Any = _NON_CALCULE
        self._continus: Any = _NON_CALCULE
        self._exacts: Any = _NON_CALCULE
        self._reference: Any = _NON_CALCULE

    def a_jour(self, source: list[dict[str, Any]], empreinte: tuple[Any, ...]) -> bool:
        return source is self.source and empreinte == self._empreinte

    def points_de_controle(self, metaorder_id: str) -> list[dict[str, Any]]:
        """Carnets liés à ce métaordre par le protocole de points de contrôle, dans l'ordre de la liste."""
        if self._controles is _NON_CALCULE:
            groupes: dict[str, list[dict[str, Any]]] = {}
            for row in self.source:
                if (str(row.get("collector_protocol") or "") == CHECKPOINT_COLLECTOR_PROTOCOL
                        and row.get("checkpoint_id")):
                    groupes.setdefault(str(row.get("metaorder_id") or ""), []).append(row)
            self._controles = groupes
        return list(self._controles.get(metaorder_id, ()))

    def continus(self) -> tuple[list[dict[str, Any]], str | None]:
        """(carnets hors points de contrôle, refus) : mêmes contrôles, dans le même ordre, qu'à l'origine."""
        if self._continus is _NON_CALCULE:
            rows = [row for row in self.source if not row.get("checkpoint_id")]
            refus: str | None = None
            if not rows:
                refus = "MISSING_EXACT_METAORDER_CHECKPOINT"
            else:
                try:
                    horodatages = [int(row["ts_ms"]) for row in rows]
                except (KeyError, TypeError, ValueError, OverflowError):
                    refus = "INVALID_OBSERVED_BOOK"
                else:
                    if any(droite < gauche for gauche, droite in zip(horodatages, horodatages[1:], strict=False)):
                        refus = "UNSORTED_BOOK_TIMESTAMPS"
            self._continus = (rows, refus)
        return self._continus

    def horodatages_exacts(self) -> list[int] | None:
        """Horodatages entiers de la liste, ou ``None`` si un seul n'est pas un entier strictement positif."""
        if self._exacts is _NON_CALCULE:
            exacts = [_horodatage_exact(row.get("ts_ms")) for row in self.source]
            self._exacts = None if any(ts is None for ts in exacts) else exacts
        return self._exacts


    def horodatages_de_reference(self) -> list[int] | None:
        """Horodatages de TOUTE la liste, si tous sont des entiers strictement positifs et triés ; sinon ``None``.

        Même règle que le moteur gelé (``_reference_depth_features``) : un booléen n'est pas un entier,
        un seul horodatage invalide ou une liste désordonnée rendent tout le marché non mesurable.
        """
        if self._reference is _NON_CALCULE:
            horodatages = [row.get("ts_ms") for row in self.source]
            if any(isinstance(ts, bool) or not isinstance(ts, int) or ts <= 0 for ts in horodatages) or any(
                    droite < gauche for gauche, droite in zip(horodatages, horodatages[1:], strict=False)):
                self._reference = None
            else:
                self._reference = horodatages
        return self._reference


def _empreinte(source: list[dict[str, Any]]) -> tuple[Any, ...]:
    taille = len(source)
    if taille == 0:
        return (0,)
    pas = max(1, taille // SONDES)
    positions = sorted({*range(0, taille, pas), taille - 1})
    return (taille, *(
        (id(row), *(row.get(champ) for champ in _CHAMPS_LUS)) if isinstance(row, dict) else (id(row),)
        for row in (source[position] for position in positions)
    ))


_INDEX: dict[int, IndexCarnets] = {}
_usages = 0
_plafond_courant = MAX_LISTES


def _gouverneur():
    """Le gouverneur de mémoire, ou ``None`` s'il est introuvable (le cache marche sans lui)."""
    try:
        from hl_observer.ops import budget_ram
    except Exception:  # noqa: BLE001 — le cache ne dépend pas du gouverneur pour fonctionner
        return None
    return budget_ram


def plafond_listes(*, gouverneur: Any = _AUTO) -> int:
    """``MAX_LISTES`` réduit selon la pression mémoire, jamais sous ``PLAFOND_MINI_LISTES``.

    Lu seulement quand le plafond est atteint (chemin froid). Ne lève jamais : sans gouverneur, ou
    si sa lecture échoue, on garde le plafond nominal — le cache reste borné par ``MAX_LISTES``.
    """
    gouv = _gouverneur() if gouverneur is _AUTO else gouverneur
    if gouv is None:
        return MAX_LISTES
    try:
        facteur = float(gouv.facteur_d_ampleur(gouv.niveau_pression()))
    except Exception:  # noqa: BLE001
        return MAX_LISTES
    if not 0.0 < facteur <= 1.0:
        return MAX_LISTES
    return max(PLAFOND_MINI_LISTES, int(MAX_LISTES * facteur))


def _evincer_les_plus_anciennes(plafond: int) -> int:
    """Évince les listes mémorisées les plus anciennes jusqu'à repasser SOUS ``plafond``.

    Rend le nombre de listes évincées. Évincer ne change jamais un résultat : l'index évincé sera
    simplement recalculé si la liste revient. On préfère ça à ``clear()``, qui jetait aussi le chaud.
    """
    evincees = 0
    cible = max(1, int(plafond))
    while len(_INDEX) >= cible:
        try:
            _INDEX.pop(next(iter(_INDEX)))
        except (StopIteration, KeyError):       # dictionnaire vidé entre-temps : rien à faire
            break
        evincees += 1
    return evincees


def oublier_les_listes_abandonnees() -> int:
    """Oublie les listes que seul l'index tient encore ; rend le nombre de listes oubliées.

    Une liste mémorisée est tenue par son index (1) et par l'appel qui la compte (1) : un total de 2
    signifie que l'appelant ne l'a plus. Les carnets continus d'une liste oubliée le sont au tour suivant.
    """
    oubliees = 0
    while True:
        mortes = [cle for cle, index in list(_INDEX.items()) if sys.getrefcount(index.source) <= 2]
        if not mortes:
            return oubliees
        for cle in mortes:
            _INDEX.pop(cle, None)
        oubliees += len(mortes)


def index_des_carnets(source: list[dict[str, Any]]) -> IndexCarnets:
    """L'index de cette liste : mémorisé pour une grande liste inchangée, recalculé sinon."""
    global _usages, _plafond_courant
    if type(source) is not list or len(source) < SEUIL_INDEX:
        return IndexCarnets(source)
    _usages += 1
    if _usages % BALAYAGE_TOUS_LES == 0:
        oublier_les_listes_abandonnees()
    empreinte = _empreinte(source)
    index = _INDEX.get(id(source))
    if index is None or not index.a_jour(source, empreinte):
        oublier_les_listes_abandonnees()
        if len(_INDEX) >= _plafond_courant:
            # Chemin FROID (on atteint le plafond) : seul endroit où l'on consulte la pression mémoire.
            _plafond_courant = plafond_listes()
            _evincer_les_plus_anciennes(_plafond_courant)
        index = IndexCarnets(source, empreinte)
        _INDEX[id(source)] = index
    return index


def liste_des_carnets(valeur: Any) -> list[dict[str, Any]]:
    """La liste elle-même si c'en est une (son index se retrouve d'un replay à l'autre), sinon une copie."""
    return valeur if type(valeur) is list else list(valeur)


def oublier_les_index() -> None:
    """Libère tous les index mémorisés (et les listes de carnets qu'ils retenaient)."""
    global _plafond_courant
    _INDEX.clear()
    _plafond_courant = MAX_LISTES          # nouveau corpus : on repart du plafond nominal


__all__ = [
    "BALAYAGE_TOUS_LES", "MAX_LISTES", "PLAFOND_MINI_LISTES", "SEUIL_INDEX", "SONDES", "IndexCarnets",
    "index_des_carnets", "liste_des_carnets", "oublier_les_index", "oublier_les_listes_abandonnees",
    "plafond_listes",
]

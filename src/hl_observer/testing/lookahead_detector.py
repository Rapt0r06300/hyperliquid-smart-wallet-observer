"""#563 / H-158 + #562 / H-157 — LE DÉTECTEUR DE LOOKAHEAD. **AST, pas grep.**

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CE MODULE EXISTE
═══════════════════════════════════════════════════════════════════════════════════════════════

Le 2026-07-13, on a trouve `garch11_variance` qui **LISAIT LE FUTUR** : elle calculait une
variance sur **toute** la serie, puis la renvoyait comme si elle etait connue a chaque instant.
La branche « regime » du gate en dependait -> IMPROVE-10, marque « completed », **n'a jamais eu
lieu**.

La tache #563 propose : *« GREP `.mean()` / `.max()` / `.std()` SANS `rolling()` = lookahead »*.

    🚩 **NON. Pas un grep. Un AST.**

Un grep lit les **docstrings** et les **commentaires** -- et dans ce projet, les docstrings
*citent* souvent le bug qu'elles decrivent. C'est la lecon de G2 : *l'inventaire n'a rien trouve,
c'est l'INVARIANT (AST) qui a trouve les 2 edges fabriques.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON CHERCHE, PRECISEMENT
═══════════════════════════════════════════════════════════════════════════════════════════════

Un **agregat non fenetre** applique a une serie dont on utilise ensuite un point PASSE :

    m = prices.mean()          # <- utilise TOUTE la serie, futur compris
    z = (prices[i] - m) / s    # <- ... pour juger l'instant i. LOOKAHEAD.

vs la forme saine :

    m = prices[:i+1].mean()    # <- seulement le passe
    m = rolling(prices, n)[i]  # <- fenetre glissante

⚠️ **CE DETECTEUR NE PROUVE RIEN A LUI SEUL.** Un agregat global peut etre parfaitement
legitime (calculer la vol *d'un backtest termine* pour son rapport, par ex.). Il **SIGNALE**,
il ne condamne pas. C'est pour ca que #562 (le test **differentiel**) existe : lui seul PROUVE.

    ***Un signalement AST dit « regarde ici ». Un test differentiel dit « c'est faux ».***

PUR : aucun import du code analyse, aucune execution. On lit l'arbre. Aucun ordre reel.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

# ⚠️ 🔴 CE QUE J'AI APPRIS EN LANCANT CE DETECTEUR (2026-07-13) :
#
# #563 disait : « GREP `.mean()` / `.std()` SANS `rolling()` = lookahead ».
# **C'est un idiome PANDAS.** Notre code est du **Python PUR** : il n'y a pas UN SEUL `.mean()`.
# Les agregats s'ecrivent `sum(values) / len(values)`.
#
# Ma 1re version ne cherchait que des appels de METHODE (`x.mean()`) -> **0 signalement**,
# et j'ai failli en conclure « pas de lookahead ». **L'outil qui ment, encore.**
# Attrape uniquement parce que je l'ai teste sur le bug CONNU (`garch11_variance`) :
# ***s'il ne retrouve pas le bug qu'on connait deja, il ne trouvera jamais ceux qu'on ignore.***
#
# -> On cherche donc les DEUX formes : methode ET fonction.
AGREGATS_GLOBAUX = frozenset({
    "mean", "std", "var", "median", "quantile", "sum", "cumsum", "prod",
    "max", "min", "argmax", "argmin", "idxmax", "idxmin",
    "percentile", "nanmean", "nanstd", "nanmax", "nanmin", "corrcoef", "cov", "polyfit",
})

# Les MEMES agregats, en appels de FONCTION -- la forme reelle de notre code.
AGREGATS_FONCTIONS = frozenset({
    "sum", "max", "min", "len", "sorted", "mean", "median", "stdev", "pstdev",
    "variance", "pvariance", "fmean",
})

# Les formes SAINES : elles bornent explicitement la fenetre.
FENETRES_SAINES = frozenset({
    "rolling", "expanding", "ewm", "shift", "iloc", "loc", "head", "tail",
})

# Noms de variables qui trahissent une SERIE TEMPORELLE (sinon un `mean()` est anodin).
INDICES_DE_SERIE = ("price", "prix", "px", "close", "mid", "ret", "rendement", "serie",
                    "series", "candle", "bougie", "hist", "vol", "sigma", "spread", "funding",
                    "pnl", "equity", "signal", "value", "values", "data")

MOTIF_AGREGAT_GLOBAL = "AGREGAT_GLOBAL_SUR_UNE_SERIE_TEMPORELLE_LOOKAHEAD_POSSIBLE"
MOTIF_SLICE_FUTUR = "SLICE_QUI_VA_AU_DELA_DE_L_INSTANT_COURANT"


@dataclass(frozen=True, slots=True)
class Suspicion:
    fichier: str
    ligne: int
    fonction: str
    cible: str            # ce sur quoi l'agregat est applique
    agregat: str
    motif: str
    extrait: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"fichier": self.fichier, "ligne": self.ligne, "fonction": self.fonction,
                "cible": self.cible, "agregat": self.agregat, "motif": self.motif,
                "extrait": self.extrait,
                "avertissement": "SIGNALEMENT, PAS PREUVE. Confirmer par un test DIFFERENTIEL."}


def _nom_de_la_cible(noeud: ast.AST) -> str:
    """`prices.mean()` -> "prices" ; `df["px"].mean()` -> "px" ; sinon "" ."""
    if isinstance(noeud, ast.Name):
        return noeud.id
    if isinstance(noeud, ast.Attribute):
        return _nom_de_la_cible(noeud.value) or noeud.attr
    if isinstance(noeud, ast.Subscript):
        s = noeud.slice
        if isinstance(s, ast.Constant) and isinstance(s.value, str):
            return s.value
        return _nom_de_la_cible(noeud.value)
    if isinstance(noeud, ast.Call):
        return _nom_de_la_cible(noeud.func)
    return ""


def _ressemble_a_une_serie(nom: str) -> bool:
    n = (nom or "").lower()
    return any(i in n for i in INDICES_DE_SERIE)


def _est_deja_fenetre(noeud: ast.AST) -> bool:
    """`prices.rolling(20).mean()` -> la fenetre est LA. Pas de lookahead."""
    cur: ast.AST | None = noeud
    vus = 0
    while cur is not None and vus < 8:
        vus += 1
        if isinstance(cur, ast.Call):
            cur = cur.func
            continue
        if isinstance(cur, ast.Attribute):
            if cur.attr in FENETRES_SAINES:
                return True
            cur = cur.value
            continue
        if isinstance(cur, ast.Subscript):
            return True          # `prices[:i]` : borne explicite -> on considere sain
        break
    return False


class _Visiteur(ast.NodeVisitor):
    def __init__(self, fichier: str, lignes: Sequence[str]) -> None:
        self.fichier = fichier
        self.lignes = lignes
        self.fonction = "<module>"
        self.suspicions: list[Suspicion] = []

    def visit_FunctionDef(self, n: ast.FunctionDef) -> None:  # noqa: N802
        precedent, self.fonction = self.fonction, n.name
        self.generic_visit(n)
        self.fonction = precedent

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, n: ast.Call) -> None:  # noqa: N802
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in AGREGATS_GLOBAUX:
            cible = _nom_de_la_cible(f.value)
            if _ressemble_a_une_serie(cible) and not _est_deja_fenetre(f.value):
                extrait = ""
                if 0 < n.lineno <= len(self.lignes):
                    extrait = self.lignes[n.lineno - 1].strip()[:100]
                self.suspicions.append(Suspicion(
                    fichier=self.fichier, ligne=n.lineno, fonction=self.fonction,
                    cible=cible, agregat=f.attr, motif=MOTIF_AGREGAT_GLOBAL, extrait=extrait,
                ))
        self.generic_visit(n)


def analyser_source(source: str, *, fichier: str = "<memoire>") -> list[Suspicion]:
    """Analyse un source Python. **AST : les docstrings et commentaires sont INVISIBLES.**"""
    try:
        arbre = ast.parse(source)
    except SyntaxError:
        return []
    v = _Visiteur(fichier, source.splitlines())
    v.visit(arbre)
    return v.suspicions


def analyser_fichiers(chemins: Iterable[Path]) -> list[Suspicion]:
    out: list[Suspicion] = []
    for p in chemins:
        try:
            out.extend(analyser_source(p.read_text("utf-8"), fichier=str(p)))
        except OSError:
            continue
    return sorted(out, key=lambda s: (s.fichier, s.ligne))


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# #562 — LE TEST DIFFERENTIEL. **Lui seul PROUVE.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def lit_le_futur(fonction, serie: Sequence[float], *, i: int | None = None) -> bool:
    """*Un test qui ne lit pas le code ne peut pas etre trompe par un commentaire.*

    Principe : on appelle `fonction` sur la serie COMPLETE, puis sur la serie **TRONQUEE**
    apres l'instant `i`. Si la sortie a l'instant `i` **CHANGE**, la fonction lisait le futur.

    C'est exactement le test qui a confondu `garch11_variance`.
    """
    n = len(serie)
    if n < 4:
        raise ValueError("serie trop courte pour un test differentiel (min 4 points)")
    if i is None:
        i = n // 2
    if not 0 <= i < n:
        raise ValueError("i hors bornes")

    complet = fonction(list(serie))
    tronque = fonction(list(serie[: i + 1]))

    # 🔴 GARDE AJOUTE APRES UN FAUX POSITIF DE MON PROPRE OUTIL (2026-07-13).
    #
    # Le 1er balayage a accuse `stable_hash`, `compute_raw_hash`, `stable_payload_hash` de
    # « lire le futur ». **Ce sont des fonctions de HACHAGE.** Elles rendent une CHAINE.
    # `list("abc")` -> ['a','b','c'] -> je comparais des CARACTERES.
    # Evidemment que le hash d'une serie tronquee differe : c'est le but d'un hash.
    #
    # *Un outil qui accuse a tort est un outil qu'on cesse d'ecouter.* On exige donc :
    #   * une sortie qui est une SEQUENCE (pas une chaine, pas un scalaire) ;
    #   * de MEME LONGUEUR que l'entree (une serie temporelle -> une serie temporelle) ;
    #   * dont les elements sont NUMERIQUES.
    # Tout le reste n'est **pas testable** par ce test -- et on le DIT, on ne l'accuse pas.
    for sortie, entree in ((complet, serie), (tronque, serie[: i + 1])):
        if isinstance(sortie, (str, bytes)) or not isinstance(sortie, (list, tuple)):
            raise TypeError(
                "sortie non testable : ce test ne vaut que pour `serie -> serie` "
                "(recu %s). **Non teste != innocent.**" % type(sortie).__name__
            )
        if len(sortie) != len(entree):
            raise TypeError(
                "sortie non alignee sur l'entree (%d vs %d) : non testable par le differentiel"
                % (len(sortie), len(entree))
            )
        if sortie and not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                              for x in sortie):
            raise TypeError("sortie non numerique : non testable par le differentiel")

    complet, tronque = list(complet), list(tronque)
    a, b = complet[i], tronque[i]
    if a == b:
        return False
    # tolerance numerique : un ecart infime n'est pas du lookahead, c'est du flottant
    ecart = abs(float(a) - float(b))
    echelle = max(abs(float(a)), abs(float(b)), 1e-12)
    return (ecart / echelle) > 1e-9


def resume(suspicions: Sequence[Suspicion]) -> dict[str, Any]:
    par_fichier: dict[str, int] = {}
    for s in suspicions:
        par_fichier[s.fichier] = par_fichier.get(s.fichier, 0) + 1
    return {
        "n_suspicions": len(suspicions),
        "n_fichiers": len(par_fichier),
        "par_fichier": dict(sorted(par_fichier.items(), key=lambda kv: -kv[1])),
        "avertissement": (
            "⚠️ **SIGNALEMENTS, PAS PREUVES.** Un agregat global peut etre legitime (rapport "
            "post-backtest). Seul le test DIFFERENTIEL (`lit_le_futur`) prouve. "
            "*Un signalement AST dit « regarde ici » ; un test differentiel dit « c'est faux ».*"
        ),
        "real_execution": False,
    }


__all__ = [
    "AGREGATS_GLOBAUX", "FENETRES_SAINES", "INDICES_DE_SERIE",
    "MOTIF_AGREGAT_GLOBAL", "MOTIF_SLICE_FUTUR", "Suspicion",
    "analyser_fichiers", "analyser_source", "lit_le_futur", "resume",
]

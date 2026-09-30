"""IDEA-93 — MUTATION TESTING, en Python pur (2026-07-13).

    « Un garde-fou qui ne peut pas echouer ne garde rien. »

Toute la journee du 13/07 tourne autour de cette phrase. Aujourd'hui j'ai trouve, dans MON PROPRE
code de garde :

  * un mot-cle de 2 caracteres qui ne pouvait matcher JAMAIS (`"rl"`) ;
  * un audit de couverture qui annoncait 0 % ;
  * un seuil qui s'effondrait a 0 quand le p95 etait negatif ;
  * une branche `if` structurellement inatteignable.

Chacun de ces bugs avait des tests VERTS autour de lui. **Le vert ne prouve rien.**

LE MUTATION TESTING EST LA SEULE MESURE HONNETE DE CE QUE VALENT NOS TESTS :
on CASSE le code exprès (on remplace `<` par `<=`, `+` par `-`, `True` par `False`...), on relance
les tests, et on regarde.

    mutant TUE     -> au moins un test a rougi   -> les tests gardaient QUELQUE CHOSE. Bien.
    mutant SURVIVANT -> tous les tests restent VERTS -> **cette ligne n'est gardee par personne.**

Le score de mutation (tues / total) est la vraie couverture. La couverture de LIGNES, elle, ne dit
que « ce code a ete EXECUTE » -- pas « ce code a ete VERIFIE ». On l'a paye : 99,4 % de couverture
annoncee, et des edges fabriques qui passaient au travers.

DENY-BY-DEFAULT : un mutant qu'on n'arrive pas a compiler n'est pas compte comme « tue » -- il est
compte INVALIDE. Sinon on gonflerait le score en cassant le code plus fort.

PUR : ce module GENERE les mutants (AST) et COMPTE le resultat. Il ne lance rien lui-meme --
`tools/muter.py` s'en charge. Aucun ordre reel : on ne mute que du code, jamais un ordre.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Iterable

# =============================================================================================
# LES MUTATIONS. Chacune est un BUG PLAUSIBLE, pas une absurdite.
# =============================================================================================
# On ne mute pas au hasard : on reproduit les fautes qu'on a REELLEMENT commises dans ce projet.
#   `>` <-> `>=`   : la borne stricte de #588 (« il aurait fallu +95,6 %, le prix a monte de
#                     +95,6 % » -> declare LIQUIDE alors qu'il survivait EXACTEMENT).
#   `<` <-> `<=`   : les seuils de refus.
#   `and` <-> `or` : le gate qui laisse passer au lieu de refuser.
#   `+` <-> `-`    : le bug de SIGNE (la fraicheur qui rendait un edge negatif MEILLEUR).
#   True <-> False : le flag mort (la pile V26 entiere etait eteinte).
#   `not`  retire  : l'inversion silencieuse d'un veto.

COMPARAISONS: dict[type, type] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
}

ARITHMETIQUE: dict[type, type] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
}

BOOLEENS: dict[type, type] = {
    ast.And: ast.Or,
    ast.Or: ast.And,
}


@dataclass(frozen=True, slots=True)
class Mutant:
    """Une seule mutation, localisee. `code` est le source COMPLET du fichier, mute."""

    fichier: str
    ligne: int
    operateur: str          # ex. "Lt->LtE"
    description: str        # lisible par un humain, dans le rapport
    code: str

    @property
    def id(self) -> str:
        return "%s:%d:%s" % (self.fichier, self.ligne, self.operateur)


# =============================================================================================
# 🔴 LES MUTANTS EQUIVALENTS -- ET MON PROPRE OUTIL QUI MENTAIT (correctif du 2026-07-13)
# =============================================================================================
# Ma 1re version a rapporte 15 « survivants ». **Dix d'entre eux etaient des FAUX.**
#
#     @dataclass(frozen=True, slots=True)      <- muter True->False ici ne change RIEN
#                                                 d'observable. Le mutant SURVIT forcement.
#
# Un mutant equivalent n'est pas un trou de test : c'est une mutation qui ne modifie pas le
# comportement. Les compter comme « survivants » fait CHUTER le score sans raison -- et un score
# faux est pire que pas de score : il ferait courir apres des fantomes.
#
# *Mon outil de mesure mentait. Encore.* (Comme l'audit de couverture qui annoncait 0 %, comme le
# seuil qui s'effondrait sur un p95 negatif.) **Suspecter son PROPRE outil avant le code d'autrui.**
#
# On EXCLUT donc les booleens qui vivent dans un DECORATEUR (`@dataclass(...)`, `@lru_cache(...)`).


def _bools_de_decorateurs(arbre: ast.AST) -> set[int]:
    """Les `id()` des constantes booleennes situees dans un decorateur : mutants EQUIVALENTS."""
    exclus: set[int] = set()
    for node in ast.walk(arbre):
        decos = getattr(node, "decorator_list", None)
        if not decos:
            continue
        for d in decos:
            for sous in ast.walk(d):
                if isinstance(sous, ast.Constant) and isinstance(sous.value, bool):
                    exclus.add(id(sous))
    return exclus


class _Muteur(ast.NodeTransformer):
    """Applique UNE mutation, a l'occurrence n° `cible`. Une seule a la fois : sinon on ne sait
    pas LAQUELLE le test a attrapee."""

    def __init__(self, cible: int, exclus: set[int] | None = None) -> None:
        self.cible = cible
        self.vu = 0
        self.exclus = exclus or set()
        self.applique: tuple[int, str] | None = None   # (ligne, "Lt->LtE")

    def _tour(self) -> bool:
        """True si c'est CETTE occurrence qu'on doit muter."""
        touche = self.vu == self.cible
        self.vu += 1
        return touche

    # ---------------------------------------------------------------- comparaisons

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            remplacant = COMPARAISONS.get(type(op))
            if remplacant is None:
                continue
            if self._tour():
                node.ops[i] = remplacant()
                self.applique = (node.lineno, "%s->%s" % (type(op).__name__, remplacant.__name__))
        return node

    # ---------------------------------------------------------------- arithmetique

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        remplacant = ARITHMETIQUE.get(type(node.op))
        if remplacant is not None and self._tour():
            ancien = type(node.op).__name__
            node.op = remplacant()
            self.applique = (node.lineno, "%s->%s" % (ancien, remplacant.__name__))
        return node

    # ---------------------------------------------------------------- and / or

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        remplacant = BOOLEENS.get(type(node.op))
        if remplacant is not None and self._tour():
            ancien = type(node.op).__name__
            node.op = remplacant()
            self.applique = (node.lineno, "%s->%s" % (ancien, remplacant.__name__))
        return node

    # ---------------------------------------------------------------- True / False

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, bool) and id(node) not in self.exclus and self._tour():
            ancien = str(node.value)
            nouveau = not node.value
            self.applique = (node.lineno, "%s->%s" % (ancien, nouveau))
            return ast.copy_location(ast.Constant(value=nouveau), node)
        return node


def _compter_cibles(arbre: ast.AST, exclus: set[int] | None = None) -> int:
    """Combien de mutations possibles dans cet arbre ?

    ⚠️ Doit compter EXACTEMENT comme `_Muteur` visite -- sinon on generait des mutants vides
    (le `cible` ne serait jamais atteint) et le score serait gonfle par des non-mutations.
    Un test le verifie (`test_le_compteur_et_le_muteur_sont_D_ACCORD`).
    """
    exclus = exclus or set()
    n = 0
    for node in ast.walk(arbre):
        if isinstance(node, ast.Compare):
            n += sum(1 for op in node.ops if type(op) in COMPARAISONS)
        elif isinstance(node, ast.BinOp):
            n += 1 if type(node.op) in ARITHMETIQUE else 0
        elif isinstance(node, ast.BoolOp):
            n += 1 if type(node.op) in BOOLEENS else 0
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            n += 0 if id(node) in exclus else 1
    return n


def generer_mutants(source: str, *, fichier: str = "<memoire>", maximum: int = 200) -> list[Mutant]:
    """Tous les mutants d'un fichier (bornes a `maximum` : une suite complete = 4 min).

    Deny-by-default : si le source ne parse pas, on ne rend RIEN. On ne devine pas.
    """
    try:
        arbre_ref = ast.parse(source)
    except SyntaxError:
        return []
    total = _compter_cibles(arbre_ref, _bools_de_decorateurs(arbre_ref))
    mutants: list[Mutant] = []
    for i in range(min(total, int(maximum))):
        arbre = ast.parse(source)                       # re-parse : l'AST est mutable
        m = _Muteur(cible=i, exclus=_bools_de_decorateurs(arbre))
        mute = ast.fix_missing_locations(m.visit(arbre))
        if m.applique is None:
            continue                                    # ne devrait jamais arriver (test dedie)
        ligne, op = m.applique
        try:
            code = ast.unparse(mute)
        except (ValueError, AttributeError, RecursionError):
            continue                                    # INVALIDE, pas « tue »
        mutants.append(Mutant(
            fichier=fichier, ligne=ligne, operateur=op,
            description="ligne %d : %s" % (ligne, op),
            code=code,
        ))
    return mutants


# =============================================================================================
# LE SCORE
# =============================================================================================


@dataclass(slots=True)
class ResultatMutation:
    """Le verdict. `survivants` est la SEULE colonne qui compte : ce sont les lignes que
    personne ne garde."""

    fichier: str
    tues: int = 0
    survivants: list[Mutant] = field(default_factory=list)
    invalides: int = 0                 # mutant qui casse a l'import : NI tue, NI survivant

    @property
    def total_valides(self) -> int:
        return self.tues + len(self.survivants)

    @property
    def score(self) -> float:
        """Part des mutants TUES. 1.0 = tout bug plausible est attrape par au moins un test."""
        n = self.total_valides
        return (self.tues / n) if n else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fichier": self.fichier,
            "tues": self.tues,
            "survivants": [
                {"ligne": m.ligne, "operateur": m.operateur, "id": m.id} for m in self.survivants
            ],
            "n_survivants": len(self.survivants),
            "invalides": self.invalides,
            "score_mutation": round(self.score, 4),
            "real_execution": False,
        }


def verdict_global(resultats: Iterable[ResultatMutation], *, plancher: float = 0.0) -> dict[str, Any]:
    """Agrege, et applique un PLANCHER si on en veut un (cliquet anti-regression).

    ⚠️ Plancher a 0.0 par defaut : **on MESURE d'abord, on exige ensuite.** Poser un seuil avant
    d'avoir le chiffre, c'est inventer un nombre -- la faute que ce projet a deja payee (#588 :
    l'arrondi de mon rapport est devenu l'entree d'un test).
    """
    rs = list(resultats)
    tues = sum(r.tues for r in rs)
    survivants = sum(len(r.survivants) for r in rs)
    n = tues + survivants
    score = (tues / n) if n else 0.0
    return {
        "fichiers": len(rs),
        "mutants_valides": n,
        "tues": tues,
        "survivants": survivants,
        "invalides": sum(r.invalides for r in rs),
        "score_mutation": round(score, 4),
        "plancher": plancher,
        "ok": score >= plancher,
        "detail": [r.as_dict() for r in rs],
        "real_execution": False,
    }


__all__ = [
    "ARITHMETIQUE", "BOOLEENS", "COMPARAISONS",
    "Mutant", "ResultatMutation", "generer_mutants", "verdict_global",
]

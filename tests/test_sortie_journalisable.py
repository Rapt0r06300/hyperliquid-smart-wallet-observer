"""Un outil doit survivre à la redirection de sa sortie vers un fichier.

MESURE DU 21/11/2026 — le défaut qui a motivé ce fichier. `tools/conduire_labo_par_tranches.py`
lisait le ruban du corpus sans peine (10 631 645 fills sur 168 pas d'une heure, en 12 s)
puis mourait sur cette ligne :

    print(f"  → {len(tranches)} tranches (budget {args.budget:,} lignes) :")

`UnicodeEncodeError: 'charmap' codec can't encode character '\\u2192'`. En console
Windows la sortie est en UTF-8, mais **redirigée vers un fichier** elle retombe sur
cp1252, qui ne porte pas la flèche. Conséquence : l'outil ne pouvait pas être
journalisé, donc pas conduit en automatique — et le seul essai qui avait abouti l'avait
été à la main, dans une console. Un succès obtenu par le chemin interactif seul n'est
pas un succès.

Le critère est précis. « Contient des accents » ne veut rien dire : cp1252 porte `é`,
`à`, `«` et `…`. Ce qui casse, c'est un caractère **hors** cp1252 — flèches, coches,
symboles mathématiques, emoji, traits de tableau. Et il ne casse que s'il est IMPRIMÉ :
le même caractère dans un commentaire ne gêne personne. On lit donc l'arbre, et on ne
regarde que les appels `print` et `.write`.

Le remède est l'idiome déjà utilisé par une dizaine d'outils du dépôt :

    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOSSIERS = ("tools", "src")
IDIOME = "reconfigure(encoding"


def _points_hors_cp1252(texte: str) -> list[int]:
    points = set()
    for caractere in set(texte):
        if ord(caractere) < 128:
            continue
        try:
            caractere.encode("cp1252")
        except UnicodeEncodeError:
            points.add(ord(caractere))
    return sorted(points)


def prints_non_journalisables(source: str) -> list[tuple[int, list[int]]] | None:
    """Les appels `print`/`.write` qui portent un caractère hors cp1252.

    Rend ``None`` si la source n'est pas analysable : on ne conclut rien d'un fichier
    qu'on ne sait pas lire, et le test ne le compte pas comme propre pour autant.
    """
    try:
        arbre = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    trouves: list[tuple[int, list[int]]] = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        cible = noeud.func
        nom = cible.attr if isinstance(cible, ast.Attribute) else getattr(cible, "id", "")
        if nom not in ("print", "write"):
            continue
        morceau = ast.get_source_segment(source, noeud) or ""
        points = _points_hors_cp1252(morceau)
        if points:
            trouves.append((noeud.lineno, points))
    return trouves


def _fichiers() -> list[Path]:
    fichiers = []
    for dossier in DOSSIERS:
        for chemin in (RACINE / dossier).rglob("*.py"):
            texte = str(chemin)
            if "__pycache__" in texte or "site-packages" in texte:
                continue
            fichiers.append(chemin)
    return sorted(fichiers)


def test_il_y_a_bien_du_code_a_verifier():
    """Un contrôle qui ne lit rien serait vert pour la pire des raisons."""
    assert len(_fichiers()) >= 500


def test_aucun_print_exotique_sans_sortie_utf8():
    """42 fichiers etaient dans ce cas le 21/11/2026 ; ils ont tous ete corriges."""
    coupables = []
    for chemin in _fichiers():
        source = chemin.read_text(encoding="utf-8", errors="replace")
        if IDIOME in source:
            continue
        dangereux = prints_non_journalisables(source)
        if dangereux:
            relatif = chemin.relative_to(RACINE).as_posix()
            coupables.append(f"{relatif}:{dangereux[0][0]} ({len(dangereux)} print(s))")
    assert not coupables, (
        "print(s) impossibles a journaliser (caractere hors cp1252 et pas d'idiome "
        f"de sortie UTF-8), {len(coupables)} fichier(s) :\n- " + "\n- ".join(coupables[:12])
    )


@pytest.mark.parametrize(
    ("source", "attendu"),
    [
        ('print("-> deux tranches")\n', 0),
        ('print("→ deux tranches")\n', 1),
        ('print(f"{n} ✓ valides")\n', 1),
        ('print("e accent aigu : é, guillemets : « »")\n', 0),
        ('# commentaire avec → une fleche\nprint("sage")\n', 0),
        ('import sys\nsys.stderr.write("→")\n', 1),
    ],
)
def test_le_discriminant_ne_regarde_que_ce_qui_est_imprime(source, attendu):
    """`é` et `«` passent en cp1252 ; une flèche non. Un commentaire n'imprime rien."""
    assert len(prints_non_journalisables(source)) == attendu


def test_une_source_inanalysable_ne_passe_pas_pour_propre():
    assert prints_non_journalisables("def f(:\n    print('x')\n") is None

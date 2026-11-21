"""Une lecture `os.environ["X"]` sans garde plante le processus sur une variable absente.

LE DEFAUT (21/11/2026). `tools/continuous_reconcile_backlog.py` finissait par :

    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as env:

`GITHUB_ENV` n'existe QUE dans GitHub Actions. Lu sans garde a la **derniere ligne** de `main()`,
APRES que tout le travail a reussi, il transformait un passage local en `KeyError` : le code 0
etait perdu et remplace par une trace. Un succes rendu comme une panne.

POURQUOI UN TEST AST ET PAS UN GREP. La regle `c_env_no_default` de l'audit du projet signalait
**24 occurrences** ; l'analyse syntaxique montre que **40 sont des ECRITURES ou des
suppressions** (`os.environ["X"] = ...`), qui ne peuvent pas lever `KeyError`, et qu'il ne
restait que **2 vraies lectures** -- dont une deja gardee. Un motif textuel ne distingue pas
lire et ecrire ; l'AST, si.
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

#: Lectures sans defaut ADMISES, avec leur raison. Toute nouvelle entree doit se justifier ici.
#: `ops/validation_portable.py` lit `os.environ[name]` juste apres
#: `if os.environ.get(name):` -- la garde est sur la ligne precedente, l'AST ne la voit pas.
LECTURES_GARDEES = {
    "src/hl_observer/ops/validation_portable.py",
}


def _lectures_sans_defaut() -> list[str]:
    trouvees: list[str] = []
    for dossier in ("src", "tools"):
        base = RACINE / dossier
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            if "site-packages" in chemin.parts or "__pycache__" in chemin.parts:
                continue
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            cibles: set[int] = set()
            for noeud in ast.walk(arbre):
                if isinstance(noeud, (ast.Assign, ast.AugAssign)):
                    pointes = (noeud.targets if isinstance(noeud, ast.Assign)
                               else [noeud.target])
                    for cible in pointes:
                        for interne in ast.walk(cible):
                            cibles.add(id(interne))
            for noeud in ast.walk(arbre):
                if not (isinstance(noeud, ast.Subscript)
                        and isinstance(noeud.value, ast.Attribute)
                        and noeud.value.attr == "environ"):
                    continue
                if id(noeud) in cibles or isinstance(noeud.ctx, ast.Del):
                    continue                      # ecriture/suppression : pas de KeyError
                relatif = chemin.relative_to(RACINE).as_posix()
                if relatif in LECTURES_GARDEES:
                    continue
                trouvees.append(f"{relatif}:{noeud.lineno} -> {ast.unparse(noeud)[:60]}")
    return sorted(trouvees)


def test_aucune_lecture_d_environ_sans_garde() -> None:
    fautives = _lectures_sans_defaut()
    assert fautives == [], (
        "lecture(s) `os.environ[...]` sans garde : une variable absente plante le processus, "
        "et le faire a la fin d'un traitement reussi perd le resultat. Utiliser "
        "`os.environ.get(...)` et decider explicitement du cas absent :\n  "
        + "\n  ".join(fautives))


def test_le_site_corrige_utilise_bien_get() -> None:
    """La moitie qui compte : sans ceci, supprimer la ligne passerait le test ci-dessus."""
    texte = (RACINE / "tools" / "continuous_reconcile_backlog.py").read_text(
        encoding="utf-8", errors="replace")
    assert 'os.environ.get("GITHUB_ENV")' in texte, (
        "la lecture gardee de GITHUB_ENV a disparu")
    assert 'os.environ["GITHUB_ENV"]' not in texte, (
        "la lecture NON gardee est revenue")


def test_la_regle_voit_la_difference_entre_lire_et_ecrire() -> None:
    """Sans ceci, une regle qui ne detecte rien passerait les deux tests ci-dessus."""
    ecriture = ast.parse('import os\nos.environ["X"] = "1"\n')
    lecture = ast.parse('import os\nv = os.environ["X"]\n')
    for arbre, attendu in ((ecriture, False), (lecture, True)):
        cibles = set()
        for n in ast.walk(arbre):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    for x in ast.walk(t):
                        cibles.add(id(x))
        vus = [n for n in ast.walk(arbre)
               if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute)
               and n.value.attr == "environ" and id(n) not in cibles]
        assert bool(vus) is attendu, f"classement errone pour {'lecture' if attendu else 'ecriture'}"

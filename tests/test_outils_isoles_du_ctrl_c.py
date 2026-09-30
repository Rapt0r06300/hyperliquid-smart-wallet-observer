"""L'INVARIANT : un outil qui lance pytest ne doit PAS mourir du Ctrl-C de pytest.

L'HISTOIRE (deux fois le meme bug, a deux jours d'ecart)
-------------------------------------------------------
Sur Windows, un Ctrl-C frappe la CONSOLE, pas un processus. Un outil qui lance la suite de tests
dans sa propre console meurt donc AVEC elle -- en emportant sa mesure.

  * 2026-07-11 : `tools/audit_report.py` en est mort. Correctif ecrit, commente, en place :
    `creationflags=CREATE_NEW_PROCESS_GROUP`.
  * 2026-07-13 : `tools/couverture_de_lignes.py` en est mort **exactement pareil**, deux fois de
    suite -- parce que le correctif de 2026-07-11 vivait dans UN fichier, et nulle part ailleurs.

C'est le motif que ce projet connait par coeur : *une capacite presente, un chainon manquant, et
personne ne se plaint*. Le poller de carnet L2 (funding repare, L2 laisse) etait le meme bug.

Corriger le 2e outil a la main ne changerait rien : le 3e le reoublierait. On pose donc un
INVARIANT, verifie par AST (pas par regex -- lecon de G2).

ZONE AVEUGLE, DITE A VOIX HAUTE
-------------------------------
Le detecteur ne voit que les commandes **litterales** (`["python", "-m", "pytest"]`) ou une
variable dont l'affectation est litterale. Une commande construite dynamiquement
(`[_py(), *sec.argv]` dans megatest) lui echappe : c'est indecidable statiquement.

On ne fait donc PAS semblant. Deux tests, deux portees :
  * le 1er verifie ce qu'il peut PROUVER (commandes litterales) ;
  * le 2e couvre nommement les LANCEURS CONNUS de la suite, ou l'isolation est exigee sur
    **tous** leurs sous-processus (l'isolation est gratuite : elle ne change rien au reste).

🚩 TROISIEME FOIS -- ET CETTE FOIS DANS L'ANGLE MORT DE CE FICHIER MEME (2026-07-13, #594)
------------------------------------------------------------------------------------------
J'ai ecrit cet invariant le matin. Il ne scannait que `tools/`. L'apres-midi, la SUITE COMPLETE
s'est arretee sur un `KeyboardInterrupt` que personne n'a tape... et le coupable etait

    tests/test_env_hermetique.py:76   subprocess.run([sys.executable, "-m", "pytest", ...])

Un TEST qui lance pytest, sans isolation de groupe. Exactement le bug que ce fichier existe pour
empecher -- hors de son perimetre de scan. *Un garde-fou qui ne regarde pas partout ne garde que
ce qu'il regarde.* Le detecteur scanne desormais `tools/` ET `tests/`.
"""

from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
OUTILS = RACINE / "tools"
TESTS = RACINE / "tests"

_LANCEURS_SUBPROCESS = {"run", "Popen", "call", "check_output", "check_call"}
_MOTS_DE_TEST = ("pytest", "coverage")

# Outils dont on SAIT qu'ils lancent la suite (commande construite dynamiquement -> l'AST ne peut
# pas le prouver). Pour eux, on exige l'isolation sur TOUS leurs sous-processus.
LANCEURS_CONNUS_DE_LA_SUITE = ("megatest.py", "audit_report.py", "couverture_de_lignes.py")


def _litteraux(noeud: ast.AST) -> str:
    return " ".join(
        n.value for n in ast.walk(noeud) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ).lower()


def _table_des_affectations(arbre: ast.AST) -> dict[str, str]:
    """`cmd = ["python", "-m", "pytest"]` -> {"cmd": "python -m pytest"}. Cas simples seulement."""
    table: dict[str, str] = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            table[n.targets[0].id] = _litteraux(n.value)
    return table


def _appels_subprocess(arbre: ast.AST) -> list[ast.Call]:
    trouves = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            base = n.func.value
            if (
                n.func.attr in _LANCEURS_SUBPROCESS
                and isinstance(base, ast.Name)
                and base.id == "subprocess"
            ):
                trouves.append(n)
    return trouves


def _lance_des_tests(appel: ast.Call, table: dict[str, str]) -> bool:
    """PROUVE que la commande lance la suite. Dans le doute -> False (on ne crie pas au hasard)."""
    if not appel.args:
        return False
    a = appel.args[0]
    texte = _litteraux(a)
    if isinstance(a, ast.Name):
        texte = (texte + " " + table.get(a.id, "")).strip()
    # `for cmd in cmds:` -> la variable de boucle n'est pas une Assign. On regarde alors les
    # litteraux de TOUTES les listes du module qui contiennent « pytest ».
    return any(m in texte for m in _MOTS_DE_TEST)


def _a_l_isolation(appel: ast.Call) -> bool:
    return any(k.arg == "creationflags" for k in appel.keywords)


def _outils() -> list[Path]:
    """`tools/` ET `tests/` : un TEST qui lance pytest tue la suite tout aussi bien qu'un outil.

    (C'est arrive : `tests/test_env_hermetique.py` relance pytest en sous-processus pour prouver
    qu'un environnement pollue ne change pas le verdict. Sans isolation, ce sous-processus a
    emporte la suite COMPLETE avec lui, en plein milieu.)
    """
    fichiers = [p for p in OUTILS.glob("*.py") if p.name != "sous_processus_isole.py"]
    fichiers += [p for p in TESTS.glob("*.py") if p.name != Path(__file__).name]
    return sorted(fichiers)


def test_INVARIANT_aucune_commande_pytest_LITTERALE_sans_isolation_du_groupe():
    """🔴 LE TEST QUI AURAIT EVITE DE PERDRE LA MESURE DEUX FOIS.

    Il ne lit pas les commentaires : il lit l'ARBRE. Un outil peut affirmer « isole » et ne pas
    l'etre. Seul `creationflags=` compte.
    """
    fautifs = []
    for f in _outils():
        src = f.read_text(encoding="utf-8", errors="replace")
        try:
            arbre = ast.parse(src)
        except SyntaxError:
            continue
        table = _table_des_affectations(arbre)
        for appel in _appels_subprocess(arbre):
            if _lance_des_tests(appel, table) and not _a_l_isolation(appel):
                fautifs.append("%s:%d" % (f.name, appel.lineno))

    assert not fautifs, (
        "Ces outils lancent la suite SANS `creationflags` : un Ctrl-C de pytest remontera a toute "
        "la console et TUERA l'outil, donc sa mesure -- comme le 2026-07-11 (audit_report) et le "
        "2026-07-13 (couverture_de_lignes).\n"
        "  -> passer par tools/sous_processus_isole.run_isole()\n"
        "  Fautifs : %s" % ", ".join(fautifs)
    )


def test_les_LANCEURS_CONNUS_isolent_TOUS_leurs_sous_processus():
    """La zone aveugle du 1er test, couverte nommement.

    megatest construit sa commande dynamiquement (`[_py(), *sec.argv]`) : indecidable par AST.
    Alors on exige l'isolation partout chez lui. Elle est GRATUITE -- elle n'empeche rien, elle
    empeche seulement de MOURIR.
    """
    fautifs = []
    for nom in LANCEURS_CONNUS_DE_LA_SUITE:
        f = OUTILS / nom
        if not f.exists():
            continue
        arbre = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        for appel in _appels_subprocess(arbre):
            if not _a_l_isolation(appel):
                fautifs.append("%s:%d" % (nom, appel.lineno))

    assert not fautifs, (
        "Un lanceur CONNU de la suite garde un sous-processus non isole : %s" % ", ".join(fautifs)
    )


def test_le_drapeau_est_NEUTRE_hors_windows_et_REEL_sur_windows():
    """L'isolation ne doit pas casser le sandbox Linux (ou le drapeau n'existe pas)."""
    import os
    import subprocess as sp
    import sys

    sys.path.insert(0, str(OUTILS))
    from sous_processus_isole import creationflags

    if os.name == "nt":
        assert creationflags() == sp.CREATE_NEW_PROCESS_GROUP
    else:
        assert creationflags() == 0, "hors Windows, on ne passe AUCUN drapeau exotique"


def test_le_detecteur_ATTRAPE_un_arbre_FABRIQUE_qui_oublie_l_isolation():
    """🚩 UN OUTIL DE MESURE QUI NE PEUT PAS ECHOUER NE MESURE RIEN (lecon du 2026-07-13).

    Mon audit de couverture annoncait 0 % et je l'ai cru. C'est le test sur arbre FABRIQUE qui l'a
    demasque. Meme discipline ici : on prouve que le detecteur voit le defaut, ET qu'il se TAIT sur
    du code correct (un faux positif coute aussi cher qu'un faux negatif).
    """
    mauvais = ast.parse("import subprocess\nsubprocess.run(['python', '-m', 'pytest', '-q'])\n")
    a = _appels_subprocess(mauvais)
    assert len(a) == 1
    assert _lance_des_tests(a[0], {}) and not _a_l_isolation(a[0])

    par_variable = ast.parse(
        "import subprocess\ncmd = ['python', '-m', 'coverage', 'run']\nsubprocess.run(cmd)\n"
    )
    b = _appels_subprocess(par_variable)
    assert _lance_des_tests(b[0], _table_des_affectations(par_variable)), (
        "le detecteur ne resout pas une commande passee par variable : c'est la forme la plus "
        "courante, il la raterait en production"
    )

    bon = ast.parse(
        "import subprocess\nsubprocess.run(['powercfg', '/query'], capture_output=True)\n"
    )
    c = _appels_subprocess(bon)
    assert not _lance_des_tests(c[0], {}), (
        "le detecteur crie sur `powercfg` : il confondrait n'importe quel sous-processus avec un "
        "lancement de tests"
    )

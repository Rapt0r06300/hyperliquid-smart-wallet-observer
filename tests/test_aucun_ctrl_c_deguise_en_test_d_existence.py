"""🔴🔴 L'INVARIANT : `os.kill(pid, 0)` EST UN CTRL-C SOUS WINDOWS (#600, 2026-07-13).

L'HISTOIRE, ET ELLE FAIT MAL
----------------------------
Pendant DEUX JOURS, un `KeyboardInterrupt` que **personne n'a tape** a tue des mesures, des
audits, et jusqu'a la suite de tests complete. J'ai accuse -- et corrige -- TROIS sous-processus
qui relancaient pytest sans isoler leur groupe :

    2026-07-11  tools/audit_report.py
    2026-07-13  tools/couverture_de_lignes.py  (+ megatest, par precaution)
    2026-07-13  tests/test_env_hermetique.py   (dans l'angle mort de mon propre invariant)

**Aucun des trois n'etait le coupable.** Les correctifs restent justes -- l'isolation de groupe
est la bonne pratique -- mais ils ne diagnostiquaient pas ce bug-la.
*Corriger n'est pas diagnostiquer.* (Meme lecon que le defaut SL/TP, deux jours plus tot.)

LE VRAI COUPABLE, EN UNE LIGNE
------------------------------
    backtesting/runtime_guards.py:26
        os.kill(pid, 0)      # « signal 0 = simple test d'existence »

Sur Unix, oui. **Sur Windows, `signal.CTRL_C_EVENT` VAUT 0**, et `os.kill()` de CPython fait
alors `GenerateConsoleCtrlEvent(0, pid)` : **un vrai Ctrl-C, envoye au GROUPE de la console.**
`test_runtime_guards.py` appelait `parent_alive(os.getpid())` -> la suite se Ctrl-C elle-meme,
au milieu de son propre run.

Et l'ironie est complete : cette fonction est le **watchdog anti-orphelin** (IMPROVE-01). Sa
raison d'etre est de PROTEGER la session. Sous Windows, elle la TUAIT.

CE QUE CE FICHIER VERROUILLE
----------------------------
Un invariant **AST** (pas un grep : un grep lirait aussi ce docstring, qui CITE le bug).
Aucun module de production ne peut appeler `os.kill(x, 0)`. Le jour ou quelqu'un reecrit ce
"simple test d'existence", la suite rougit.

Aucun ordre reel.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

from hl_observer.backtesting.runtime_guards import parent_alive

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src" / "hl_observer"


# ============================================================ 1. L'INVARIANT (AST)


def _appels_os_kill(arbre: ast.AST) -> list[ast.Call]:
    """`os.kill(...)` ou `kill(...)` importe de os. Par l'AST -- une regex lirait ce docstring."""
    out: list[ast.Call] = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr == "kill":
            if isinstance(f.value, ast.Name) and f.value.id == "os":
                out.append(n)
        elif isinstance(f, ast.Name) and f.id == "kill":
            out.append(n)
    return out


def _signal_est_zero(appel: ast.Call) -> bool:
    """Le 2e argument vaut-il 0 (== CTRL_C_EVENT sous Windows) ? Dans le doute -> False."""
    if len(appel.args) < 2:
        return False
    sig = appel.args[1]
    return isinstance(sig, ast.Constant) and sig.value == 0


def _teste_la_plateforme(test: ast.expr) -> bool:
    """L'expression parle-t-elle de `os.name` ou de `sys.platform` ?"""
    for n in ast.walk(test):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if (n.value.id, n.attr) in {("os", "name"), ("sys", "platform")}:
                return True
    return False


def _zones_qui_REFUSENT_windows(arbre: ast.AST) -> list[tuple[int, int]]:
    """Les fonctions dont la 1re instruction est `if <plateforme Windows>: raise ...`.

    C'est la SEULE tolerance accordee a `os.kill(pid, 0)` : un appel enferme dans une fonction
    qui LEVE avant de l'atteindre sous Windows est physiquement inexecutable la-bas. Ce n'est
    pas un commentaire rassurant -- c'est une garde que la machine execute.

    Tout le reste (un simple `if os.name == "nt": return ...` ailleurs dans le fichier, un
    commentaire « POSIX seulement », une convention) ne compte PAS.
    """
    zones: list[tuple[int, int]] = []
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for stmt in fn.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                continue                                  # docstring
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                continue
            if (
                isinstance(stmt, ast.If)
                and _teste_la_plateforme(stmt.test)
                and any(isinstance(n, ast.Raise) for n in stmt.body)
            ):
                zones.append((fn.lineno, getattr(fn, "end_lineno", fn.lineno)))
            break                                         # seule la 1re instruction utile compte
    return zones


def _modules_de_production() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.as_posix())


def test_INVARIANT_aucun_module_de_production_n_appelle_os_kill_avec_le_signal_ZERO():
    """🔴 LE TEST QUI AURAIT FAIT GAGNER DEUX JOURS.

    `os.kill(pid, 0)` n'est PAS portable. Sous Windows, c'est un Ctrl-C a toute la console.
    Le remplacant est `runtime_guards._existe_sous_windows` (OpenProcess + GetExitCodeProcess :
    on INTERROGE le systeme, on ne lui ENVOIE rien).

    SEULE TOLERANCE : une fonction qui REFUSE Windows des sa 1re instruction (`raise`). C'est
    ainsi que vit le repli POSIX legitime -- et l'invariant a d'ailleurs commence par attraper
    MON PROPRE repli. Je n'ai pas affaibli le detecteur : j'ai isole l'idiome derriere un refus
    que la machine execute. *Durcir n'est pas contourner.*
    """
    coupables = []
    for f in _modules_de_production():
        try:
            arbre = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        sous_garde = _zones_qui_REFUSENT_windows(arbre)
        for appel in _appels_os_kill(arbre):
            if not _signal_est_zero(appel):
                continue
            if any(d <= appel.lineno <= f_ for d, f_ in sous_garde):
                continue
            coupables.append("%s:%d" % (f.relative_to(RACINE).as_posix(), appel.lineno))

    assert not coupables, (
        "`os.kill(pid, 0)` trouve dans du code de PRODUCTION : %s\n\n"
        "Sous Windows, signal 0 == CTRL_C_EVENT -> GenerateConsoleCtrlEvent -> un VRAI Ctrl-C "
        "envoye a TOUTE la console. Ce n'est pas un test d'existence : c'est une arme.\n"
        "  -> passer par `runtime_guards.parent_alive()`, qui INTERROGE le systeme (OpenProcess) "
        "au lieu de lui ENVOYER un signal." % ", ".join(coupables)
    )


def test_le_detecteur_ATTRAPE_un_arbre_FABRIQUE_et_se_TAIT_sur_le_code_sain():
    """🚩 UN GARDE-FOU QUI NE PEUT PAS ECHOUER NE GARDE RIEN (lecon du 13/07, deja payee 2 fois).

    On lui donne la VRAIE ligne coupable, puis du code honnete. Il doit voir la premiere et se
    taire sur le second -- un faux positif coute aussi cher qu'un faux negatif.
    """
    coupable = ast.parse("import os\nos.kill(pid, 0)\n")
    assert len(_appels_os_kill(coupable)) == 1
    assert _signal_est_zero(_appels_os_kill(coupable)[0]), "l'invariant ne voit PAS la vraie ligne"

    # un VRAI kill (SIGTERM) n'est pas notre affaire : il TUE, mais il ne ment pas sur ce qu'il fait
    honnete = ast.parse("import os\nimport signal\nos.kill(pid, signal.SIGTERM)\n")
    assert not _signal_est_zero(_appels_os_kill(honnete)[0]), "faux positif sur un kill EXPLICITE"

    # et un `kill` qui n'a rien a voir (methode d'objet) ne doit pas etre attrape
    autre = ast.parse("proc.kill()\n")
    assert _appels_os_kill(autre) == [], "faux positif : `proc.kill()` n'est pas `os.kill`"


def test_la_TOLERANCE_ne_s_ouvre_QUE_sur_une_garde_QUE_LA_MACHINE_EXECUTE():
    """🚩 LA TOLERANCE EST LA PORTE DEROBEE DE TOUT INVARIANT. On la teste comme telle.

    Un `raise` sous Windows = la ligne est inatteignable la-bas -> tolere.
    Un simple `return`, un commentaire, une convention = **rien du tout** -> refuse.
    C'est exactement la difference entre une garde et une intention.
    """
    protege = ast.parse(
        'def f(pid):\n'
        '    """docstring"""\n'
        '    import os\n'
        '    if os.name == "nt":\n'
        '        raise RuntimeError("interdit")\n'
        '    os.kill(pid, 0)\n'
    )
    assert _zones_qui_REFUSENT_windows(protege), "une garde qui LEVE doit ouvrir la tolerance"
    appel = _appels_os_kill(protege)[0]
    assert any(d <= appel.lineno <= f for d, f in _zones_qui_REFUSENT_windows(protege))

    # une garde qui se contente de RENDRE ne protege rien : sous Windows, la ligne reste atteignable
    # par tout autre chemin. Elle ne doit PAS ouvrir la tolerance.
    mou = ast.parse(
        'def f(pid):\n'
        '    import os\n'
        '    if os.name == "nt":\n'
        '        return True\n'
        '    os.kill(pid, 0)\n'
    )
    assert not _zones_qui_REFUSENT_windows(mou), "un `return` a ete pris pour une garde"

    # et une fonction SANS aucune garde, evidemment pas
    nu = ast.parse('def f(pid):\n    import os\n    os.kill(pid, 0)\n')
    assert not _zones_qui_REFUSENT_windows(nu)


# ============================================================ 2. LE COMPORTEMENT, PAR EXECUTION


def test_parent_alive_dit_VRAI_pour_nous_memes_SANS_se_Ctrl_C():
    """Le test qui, avant, TUAIT la suite. S'il passe jusqu'au bout, le Ctrl-C n'a pas eu lieu."""
    assert parent_alive(os.getpid()) is True


def test_parent_alive_dit_FAUX_pour_un_process_REELLEMENT_mort():
    """La preuve par execution : on lance un process, on attend sa mort, on interroge son PID.

    Un test d'existence qui repond « vivant » sur un mort ferait tourner des orphelins pour
    toujours ; un qui repond « mort » sur un vivant ferait s'auto-terminer la simulation.
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0),
    )
    proc.wait(timeout=30)
    assert parent_alive(proc.pid) is False, (
        "le watchdog croit VIVANT un process mort : les orphelins ne se termineraient jamais"
    )


def test_parent_alive_refuse_les_PID_absurdes_sans_planter():
    """Non-regression du fuzzing du 11/07 : un PID hors bornes faisait CRASHER le watchdog."""
    assert parent_alive(-1) is False
    assert parent_alive(0) is False
    assert parent_alive(2**63) is False
    assert parent_alive("pas_un_pid") is False
    assert parent_alive(None) is False

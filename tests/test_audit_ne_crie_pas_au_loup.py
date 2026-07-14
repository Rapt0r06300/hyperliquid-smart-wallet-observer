"""UN FAUX POSITIF PERMANENT EST PIRE QU'UNE ABSENCE DE CONTROLE (2026-07-12).

LE BUG
------
Le controle 163 de l'audit ("Suite de tests complete") declarait `ECHEC BLOQUANT` avec ce test :

    if "Timeout" in out or "timeout" in out.lower():

Or l'audit lance pytest avec `--timeout=180`, et pytest-timeout imprime dans l'ENTETE de CHAQUE
session :

    timeout: 180.0s
    timeout method: thread

Le mot etait donc **toujours** present. **L'audit ne pouvait structurellement jamais etre vert.**

Tant que la suite avait de vrais echecs, le faux se cachait derriere les vrais. Le jour ou la
suite est passee a 3 246 / 3 246 (0 echec), le fantome est reste seul -- et l'audit a continue
d'annoncer « LE CODE EST CASSE, NE PAS COMMITER ».

Une alarme qui sonne toujours n'est plus une alarme.

Ces tests exigent que la detection cherche des PREUVES (une banniere, un test FAILED nomme),
plus un mot dans un flux de 3 000 lignes.

Aucun ordre reel.
"""
from __future__ import annotations

from tools.audit_report import un_test_a_ete_tue_par_le_timeout as tue_par_timeout

# --------------------------------------------------------------- ce qui ne doit PAS declencher

ENTETE_NORMALE = """\
============================= test session starts =============================
platform win32 -- Python 3.14.0, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\\Users\\flo\\Desktop\\Projet invest
plugins: timeout-2.4.0, cov-6.0.0
timeout: 180.0s
timeout method: thread
timeout func_only: False
collected 3246 items

tests/test_ws_timeout_recovery.py::test_le_ws_repart_apres_un_timeout PASSED [ 42%]
============== 3246 passed, 22051 warnings in 199.08s (0:03:19) ===============
"""


def test_une_suite_100_pourcent_verte_ne_declenche_PAS_l_alarme():
    """LE TEST QUI COMPTE. 3 246 passed, 0 failed -> l'audit doit etre VERT.

    L'entete contient trois fois le mot "timeout" (c'est pytest-timeout qui l'ecrit) et un test
    s'appelle `test_ws_timeout_recovery`. Aucun de ces mots n'est un echec.
    """
    assert tue_par_timeout(ENTETE_NORMALE) is False, (
        "l'audit crie au loup sur sa propre entete : il ne pourra JAMAIS etre vert"
    )


def test_un_nom_de_test_contenant_timeout_ne_declenche_pas_l_alarme():
    assert tue_par_timeout(
        "tests/test_engine_freeze_ws_timeout.py::test_timeout_du_stream PASSED [ 12%]"
    ) is False


# --------------------------------------------------------------- ce qui DOIT declencher

def test_un_test_reellement_tue_declenche_l_alarme():
    """Le gate ne doit pas devenir aveugle non plus : un VRAI timeout doit sonner."""
    assert tue_par_timeout(
        "E       Failed: Timeout >180.0s\n"
        "FAILED tests/test_lent.py::test_qui_bloque - Failed: Timeout >180.0s"
    ) is True


def test_la_banniere_de_pytest_timeout_declenche_l_alarme():
    assert tue_par_timeout(
        "+++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++\n"
        "~~~~~~~~~~~~~ Stack of MainThread ~~~~~~~~~~~~~"
    ) is True


def test_le_dump_faulthandler_declenche_l_alarme():
    assert tue_par_timeout(
        "Timeout (0:02:00)!\nThread 0x00001234 (most recent call first):"
    ) is True

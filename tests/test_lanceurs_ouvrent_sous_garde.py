"""Un lanceur qui ouvre une FENÊTRE doit pouvoir s'en abstenir : la garde ``CV_NO_OPEN``.

LE FAIT (20/11/2026). La passe sûre de ``tools/tester_cmds.py`` est restée **bloquée 60 minutes**
après deux lanceurs sur douze. Cause : ``RAPPORT-COLLECTEURS.cmd`` finit en 19 s puis fait
``start "" notepad ...`` sur ses deux rapports. Notepad **hérite du tuyau de sortie** et ne le
ferme jamais, donc le lecteur du harnais attend un EOF qui n'arrive pas. Le lanceur gardait
pourtant correctement ses ouvertures derrière ``CV_NO_OPEN`` — c'est le harnais qui ne posait pas
la variable. Elle y est désormais, et ``Certificateur Coffre Fort.cmd``, qui ouvrait
``SUIVI_COFFRE.cmd`` dans une console séparée sans garde, l'a reçue aussi.

CE QUE CE TEST TIENT. Toute nouvelle ouverture de fenêtre ajoutée à un lanceur devra porter la
garde, sinon la prochaine passe se bloquera de la même façon — et un blocage de cette nature ne
se distingue pas d'un travail long, donc personne ne le cherchera là.

POURQUOI LA RÈGLE EST SI ÉTROITE. Un premier comptage grossier (``start``, ``notepad``,
``explorer``) a produit **quatre faux positifs sur cinq** : le mot « explorer » apparaît dans des
commentaires et des ``echo`` (le module « explorer autonome »), et ``LANCER_HYPERSMART.cmd``
contient 23 ``start "" /b`` — qui lancent des processus de FOND, **sans** fenêtre, et c'est voulu.
Un contrôle qui crie au loup apprend à l'opérateur à l'ignorer : la règle ne retient donc qu'une
nouvelle CONSOLE, et sa précision est vérifiée ci-dessous.
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

#: ``start ""`` suivi d'une cible, hors commentaire/echo, et SANS ``/b`` (qui n'ouvre rien).
OUVRE_UNE_FENETRE = re.compile(
    r'^\s*(?!rem\b)(?!echo\b).*?\bstart\s+""\s+(?!/b\b)(?!/B\b)\S', re.I)


def _lanceurs() -> list[Path]:
    return sorted(RACINE.glob("*.cmd"))


def test_tout_lanceur_qui_ouvre_une_fenetre_porte_la_garde() -> None:
    fautifs: list[str] = []
    gardes = 0
    for fichier in _lanceurs():
        lignes = fichier.read_text(encoding="utf-8", errors="replace").splitlines()
        ouvertures = [(n, ligne.strip()) for n, ligne in enumerate(lignes, 1)
                      if OUVRE_UNE_FENETRE.match(ligne)]
        if not ouvertures:
            continue
        if "NO_OPEN" in "\n".join(lignes):
            gardes += 1
            continue
        fautifs.extend(f"{fichier.name}:{n} -> {ligne[:90]}" for n, ligne in ouvertures)
    assert not fautifs, (
        "lanceur(s) ouvrant une fenetre sans garde CV_NO_OPEN :\n  " + "\n  ".join(fautifs))
    assert gardes >= 2, (
        "au moins deux lanceurs ouvrent une fenetre sous garde "
        "(RAPPORT-COLLECTEURS et Certificateur Coffre Fort) ; "
        f"{gardes} trouve(s) -- la regle ne detecte plus rien, donc elle ne protege plus rien")


def test_la_regle_ignore_un_processus_de_fond() -> None:
    """La moitié qui compte : ``/b`` ne doit JAMAIS être signalé.

    ``LANCER_HYPERSMART.cmd`` en contient 23. Les signaler rendrait ce test ininterrompable, et
    poser ``CV_NO_OPEN`` sur eux **empêcherait les collecteurs de démarrer**.
    """
    assert not OUVRE_UNE_FENETRE.match('start "" /b "%PY%" -m hl_observer.ops.moniteur_sante')
    assert not OUVRE_UNE_FENETRE.match('  start "" /B "%PY%" worker.py')


def test_la_regle_ignore_commentaires_et_echo() -> None:
    """« explorer » est le nom d'un module du projet, pas l'explorateur de fichiers."""
    assert not OUVRE_UNE_FENETRE.match("rem AlinaSync rapatrie aussi le feed explorer")
    assert not OUVRE_UNE_FENETRE.match("echo   + explorer autonome : decouvre les traders ACTIFS")


def test_la_regle_attrape_bien_une_vraie_ouverture() -> None:
    """Sans ceci, les trois tests ci-dessus passeraient avec une regex qui ne matche rien."""
    assert OUVRE_UNE_FENETRE.match('start "" notepad "runtime\\logs\\rapport.log"')
    assert OUVRE_UNE_FENETRE.match('if exist "%CV_ROOT%X.cmd" start "" "%CV_ROOT%X.cmd"')

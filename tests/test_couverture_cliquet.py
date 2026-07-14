"""IMPROVE-14 (#121) — le cliquet : le nombre de modules non testés ne peut plus MONTER.

« Étendre la couverture de tests » est un vœu, et un vœu ne garde rien.
Ce test transforme le vœu en **contrainte** : on ne promet pas 100 %, on interdit de reculer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.audit.couverture import auditer, ecrire_baseline, lire_baseline

RACINE = Path(__file__).resolve().parents[1]
IGNORE = ("__pycache__", "_archive", "DISABLED")


def _collecter(motifs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for motif in motifs:
        for p in RACINE.glob(motif):
            rel = p.relative_to(RACINE).as_posix()
            if any(x in rel for x in IGNORE):
                continue
            try:
                out[rel] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
    return out


def _verdict():
    py = _collecter(("src/**/*.py", "tests/**/*.py"))
    lanceurs = _collecter(("*.cmd", "*.ps1", "*.sh", "tools/**/*.cmd", "tools/**/*.ps1"))
    return auditer(py, lanceurs)


def test_le_CLIQUET_tient(capsys):
    """🔴 L'INVARIANT. Le nombre de modules joignables SANS test ne doit pas augmenter.

    Un module joignable est un module qui peut S'EXECUTER en production. S'il n'est couvert par
    aucun test, on expedie du code que personne n'a jamais eprouve. Le cliquet n'exige pas la
    perfection : il exige qu'on n'empire pas.
    """
    v = _verdict()
    baseline = lire_baseline(RACINE)

    with capsys.disabled():
        print(
            "\n[COUVERTURE] joignables=%d  couverts=%d  NON TESTES=%d  (%.1f %%)  baseline=%s"
            % (v.n_joignables, v.n_couverts, v.n_non_testes, 100 * v.taux, baseline)
        )

    assert baseline is not None, (
        "aucune baseline : lancer `python -m hl_observer.audit.couverture` (ou le .cmd) une fois "
        "pour la poser. Sans baseline, ce test ne garde rien."
    )
    assert v.n_non_testes <= baseline, (
        "🔴 REGRESSION DE COUVERTURE : %d modules joignables sans test (baseline : %d).\n"
        "%d module(s) de plus qu'avant. Les derniers de la liste :\n  %s\n\n"
        "Ce n'est pas une alarme cosmetique : un module JOIGNABLE peut s'executer en production. "
        "S'il n'a aucun test, on expedie du code que personne n'a jamais eprouve.\n"
        "Ecris son test -- ne releve pas la barre."
        % (
            v.n_non_testes,
            baseline,
            v.n_non_testes - baseline,
            "\n  ".join(v.non_testes[-10:]),
        )
    )


def test_la_baseline_ne_peut_PAS_etre_relevee(tmp_path):
    """Un cliquet qui se relâche tout seul n'est pas un cliquet : c'est une décoration.

    Si `ecrire_baseline` acceptait de monter, il suffirait de relancer l'outil après avoir
    ajouté du code non testé pour faire taire l'alarme. On vérifie qu'il REFUSE.
    """
    ecrire_baseline(tmp_path, 100)
    assert lire_baseline(tmp_path) == 100

    ecrire_baseline(tmp_path, 90)          # descendre : autorise
    assert lire_baseline(tmp_path) == 90

    with pytest.raises(ValueError, match="REFUS"):
        ecrire_baseline(tmp_path, 91)      # remonter : INTERDIT
    assert lire_baseline(tmp_path) == 90   # et rien n'a bouge


def test_l_audit_de_couverture_se_teste_sur_un_arbre_FABRIQUE():
    """Un outil qu'on ne peut pas éprouver sur des cas connus finit par se tromper en silence.

    (Leçon du 12/07 : mon propre audit contaminait ses tests. Depuis, tout outil d'audit doit
    être PUR et vérifiable sur des entrées fabriquées.)
    """
    fichiers = {
        "src/hl_observer/__main__.py": "from hl_observer import vu\n",
        "src/hl_observer/vu.py": "X = 1\n",
        "src/hl_observer/jamais_vu.py": "Y = 2\n",   # joignable ? non : personne ne l'importe
        "tests/test_vu.py": "from hl_observer import vu\n",
    }
    v = auditer(fichiers, {})
    assert "hl_observer.vu" not in v.non_testes, "`vu` est importe par un test : il est couvert"
    assert v.n_couverts >= 1

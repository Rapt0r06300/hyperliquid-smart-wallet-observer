"""#596 — LA VRAIE COUVERTURE : celle des LIGNES EXECUTEES.

POURQUOI CE SECOND OUTIL EXISTE
-------------------------------
Le cliquet de #121 mesure : *« ce module est-il IMPORTE, meme transitivement, par un test ? »*
Reponse : 481 modules sur 484 -> **99,4 %**.

**Ce chiffre flatte.** Un module importe par un test qui ne l'appelle JAMAIS compte comme
« couvert ». C'est une borne OPTIMISTE, et un joli pourcentage finit toujours par etre lu comme
un brevet de qualite.

Cet outil mesure la seule chose qui compte vraiment : **quelles LIGNES s'executent** quand la
suite tourne. Et il publie les DEUX chiffres **cote a cote** -- pour qu'aucun des deux ne puisse
mentir tout seul.

    python tools/couverture_de_lignes.py            # mesure + pose/abaisse le cliquet
    python tools/couverture_de_lignes.py --lire     # lit la baseline sans rien lancer

⚠️ Necessite `coverage` (`pip install coverage`). S'il est absent, l'outil le DIT au lieu de
faire semblant -- une mesure absente doit se voir.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sous_processus_isole import run_isole as _run_isole  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
BASELINE = RACINE / "tools" / "couverture_lignes_baseline.json"


def _lire_baseline() -> float | None:
    if not BASELINE.exists():
        return None
    try:
        return float(json.loads(BASELINE.read_text(encoding="utf-8"))["min_pct_lignes"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _ecrire_baseline(pct: float, n_tests: int) -> None:
    """Le cliquet ne tourne que vers le HAUT (la couverture ne doit pas BAISSER).

    Symetrique de #121, ou le nombre de modules non testes ne peut que DESCENDRE.
    Dans les deux cas : **on n'assouplit jamais la barre pour faire taire l'alarme.**
    """
    actuel = _lire_baseline()
    if actuel is not None and pct < actuel:
        raise ValueError(
            "REFUS d'abaisser la baseline (%.2f %% -> %.2f %%). La couverture de lignes ne doit "
            "pas RECULER. Si du code non teste vient d'etre ajoute, il faut le TESTER." % (actuel, pct)
        )
    BASELINE.write_text(
        json.dumps(
            {
                "min_pct_lignes": round(float(pct), 2),
                "tests_executes": int(n_tests),
                "note": (
                    "#596 — couverture de LIGNES executees (coverage.py). A lire A COTE de "
                    "tools/couverture_baseline.json (#121), qui mesure seulement « importe par un "
                    "test » : ce dernier est une borne OPTIMISTE. Deux chiffres, deux questions. "
                    "`tests_executes` est la CONTRE-EXPERTISE de la mesure elle-meme (#599) : une "
                    "couverture calculee sur une suite TRONQUEE est une couverture FAUSSE."
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


# ==================================================================================================
# 🔴🔴 #599 — LA MESURE DU 13/07 A 14:07 ETAIT FAUSSE, ET L'OUTIL NE LE SAVAIT PAS.
# ==================================================================================================
# `sous_processus_isole` protege l'OUTIL du Ctrl-C de la suite. Il ne protege PAS la suite d'ELLE-
# MEME : `os.kill(pid, 0)` (== CTRL_C_EVENT sous Windows, cf. #600) l'interrompait de l'interieur,
# a ~70 %. pytest affichait alors tranquillement « 2242 passed » -- et coverage calculait un
# pourcentage sur une suite AMPUTEE de 1 278 tests. Des modules apparaissaient a **0 %** simplement
# parce que leurs tests n'avaient jamais eu lieu.
#
# Une couverture mesuree sur une suite tronquee n'est pas « approximative ». Elle est FAUSSE, et
# elle accuse a tort du code parfaitement teste. L'outil doit donc REFUSER de publier une mesure
# issue d'un run interrompu -- au lieu de rendre un joli nombre.
#
# *Un instrument qui ne sait pas dire « je n'ai pas pu mesurer » ment a chaque panne.*
# ==================================================================================================

_MARQUEURS_D_INTERRUPTION = (
    "KeyboardInterrupt",
    "!!!! ",                       # pytest encadre ainsi ses arrets brutaux
    "Interrupted:",
    "stopping after",
)


def _run_interrompu(sortie: str) -> str | None:
    """Rend le marqueur trouve si la suite a ete INTERROMPUE, sinon None."""
    for m in _MARQUEURS_D_INTERRUPTION:
        if m in sortie:
            return m.strip()
    return None


def _tests_executes(sortie: str) -> int:
    """Le nombre de tests que pytest declare avoir passes. 0 si on ne sait pas lire."""
    import re

    total = 0
    for n, _ in re.findall(r"(\d+) (passed|failed|error|xfailed)", sortie):
        total += int(n)
    return total


def _pct_depuis_coverage() -> tuple[float, int] | None:
    """Lance la suite sous `coverage` et rend (% de LIGNES executees, nb de tests). None si KO."""
    try:
        import coverage  # noqa: F401
    except ImportError:
        print("coverage n'est pas installe. `pip install coverage` puis relancer.")
        print("-> AUCUNE mesure produite. Une mesure absente doit se VOIR, pas se deviner.")
        return None

    env_src = str(RACINE / "src")
    # 🔴 BUG TROUVE LE 2026-07-13 : la mesure mourait sur un `KeyboardInterrupt` que PERSONNE n'a
    # tape (cf. #600). `_run_isole` (CREATE_NEW_PROCESS_GROUP) protege l'outil -- mais PAS la suite
    # d'elle-meme. D'ou le controle d'integrite ci-dessous.
    r = _run_isole(
        [sys.executable, "-m", "coverage", "run", "--source", env_src, "-m", "pytest", "-q",
         "-p", "no:cacheprovider", "--tb=no"]
    )
    sortie = (r.stdout or "") + (r.stderr or "")

    marqueur = _run_interrompu(sortie)
    if marqueur:
        print("=" * 78)
        print("  🔴 SUITE INTERROMPUE (« %s ») -> AUCUNE MESURE PUBLIEE." % marqueur)
        print("=" * 78)
        print("  Une couverture calculee sur une suite tronquee est FAUSSE : elle accuse du code")
        print("  parfaitement teste d'etre mort, simplement parce que ses tests n'ont pas tourne.")
        print("  C'est EXACTEMENT ce qui s'est passe le 13/07 a 14:07 (cf. #599/#600).")
        print(sortie[-1500:])
        return None

    n_tests = _tests_executes(sortie)
    if n_tests <= 0:
        print("Aucun test n'a ete compte dans la sortie de pytest -> mesure NON publiee.")
        print(sortie[-1500:])
        return None

    rj = _run_isole([sys.executable, "-m", "coverage", "json", "-o", str(RACINE / "coverage.json")])
    if rj.returncode != 0:
        print(rj.stdout[-2000:])
        print(rj.stderr[-2000:])

    fichier = RACINE / "coverage.json"
    if not fichier.exists():
        print("coverage.json absent : la mesure n'a pas abouti.")
        return None
    data = json.loads(fichier.read_text(encoding="utf-8"))
    return float(data["totals"]["percent_covered"]), n_tests


def main() -> int:
    if "--lire" in sys.argv:
        print("baseline couverture de LIGNES : %s" % _lire_baseline())
        return 0

    mesure = _pct_depuis_coverage()
    if mesure is None:
        return 2
    pct, n_tests = mesure

    avant = _lire_baseline()
    print()
    print("=" * 72)
    print("  LES DEUX CHIFFRES, COTE A COTE (aucun ne dit la meme chose)")
    print("=" * 72)
    print("  #121  modules IMPORTES par un test ......... borne OPTIMISTE (voir baseline)")
    print("  #596  LIGNES reellement EXECUTEES .......... %.2f %%" % pct)
    print("  #599  tests reellement EXECUTES ............ %d" % n_tests)
    print("        (une couverture mesuree sur une suite TRONQUEE est une couverture FAUSSE)")
    print("=" * 72)
    print()

    if avant is None or pct > avant:
        _ecrire_baseline(pct, n_tests)
        print("-> baseline de lignes posee a %.2f %%" % pct)
    elif pct < avant:
        print("-> 🔴 REGRESSION : la couverture de lignes a BAISSE (%.2f %% -> %.2f %%)." % (avant, pct))
        print("   La baseline n'est PAS abaissee. Ecris les tests manquants.")
        return 1
    else:
        print("-> inchangee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

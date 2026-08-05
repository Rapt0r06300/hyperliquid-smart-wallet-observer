"""AUD-046 — LES COLLECTEURS LEGACY DU LANCEUR SONT MORTS (inatteignables), et le RESTENT.

Dans `LANCER_HYPERSMART.cmd`, la sous-routine `:demarrer_collecteurs` demarre reellement les
collecteurs par UNE seule ligne — le profil HARVEST du superviseur :

    "%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous harvest
    exit /b %ERRORLEVEL%

Ce `exit /b` COUPE le chemin principal. Tout ce qui suit dans la sous-routine (le bloc marque
« REFERENCE LEGACY CONSERVEE, MAIS INATTEIGNABLE » : une vingtaine de vieilles lignes
`start "" /b tools\\boucle_collecteur.cmd <collecteur> ...`) est du code MORT : conserve pour
reference, jamais execute sur le chemin normal. Aucun test ne l'attestait — donc rien n'empechait
qu'une de ces lignes soit un jour redeplacee AVANT le `exit /b` et se remette a demarrer un
collecteur en DOUBLE du superviseur (double collecte, PID non traces, exactement la derive que le
registre unique cherche a fermer).

Ce test verrouille l'invariant : dans `:demarrer_collecteurs`, le vrai demarrage precede le
`exit /b`, et CHAQUE ligne legacy `start ...boucle_collecteur.cmd...` est STRICTEMENT apres ce
`exit /b`. Il rougit si une ligne legacy repasse avant.

Lecture seule / paper : ce test lit le .cmd, il ne l'execute ni ne le modifie.
"""
from __future__ import annotations

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
LANCEUR = RACINE / "LANCER_HYPERSMART.cmd"

# Collecteurs legacy explicitement cites par l'audit AUD-046 (sous-ensemble garanti du bloc mort).
LEGACY_CITES = (
    "marks-collector",
    "bbo-collector",
    "experimental-paper",
    "copy-whitelist",
    "rapport-quotidien",
    "research-lab",
    "lab-microstructure",
)


def _lignes() -> list[str]:
    return LANCEUR.read_text(encoding="utf-8", errors="ignore").splitlines()


def _est_label(ligne: str) -> bool:
    """Definition d'un label batch (`:mon_label`), jamais un `goto :x` ni un commentaire `::`."""
    s = ligne.strip()
    return s.startswith(":") and not s.startswith("::")


def _est_start_collecteur(ligne: str) -> bool:
    """Ligne QUI DEMARRE reellement un collecteur : `start ... boucle_collecteur.cmd ...`.
    Exclut `REM start ...` (commentee) et `cmd /c start ...` (relance ciblee, ailleurs, ATTEIGNABLE)."""
    s = ligne.strip()
    return s.lower().startswith("start ") and "boucle_collecteur.cmd" in s


def _analyse() -> dict[str, object]:
    """Ancre l'analyse sur le VRAI texte du .cmd, borne a la sous-routine :demarrer_collecteurs.

    On scope a la sous-routine (du label `:demarrer_collecteurs` au label suivant) : ainsi une
    ligne `cmd /c start ...boucle_collecteur.cmd userfills-live...` REELLEMENT atteignable dans une
    autre sous-commande (restart-userfills) ne pollue pas l'invariant.
    """
    lignes = _lignes()
    debut = next(i for i, l in enumerate(lignes)
                 if l.strip().lower() == ":demarrer_collecteurs")
    fin = next((i for i in range(debut + 1, len(lignes)) if _est_label(lignes[i])), len(lignes))
    idx_harvest = next(
        i for i in range(debut, fin)
        if "superviseur_collecteurs demarrer-tous harvest" in lignes[i]
    )
    idx_exit = next(
        i for i in range(idx_harvest + 1, fin)
        if lignes[i].strip().lower().startswith("exit /b")
    )
    starts = [i for i in range(debut, fin) if _est_start_collecteur(lignes[i])]
    return {
        "lignes": lignes,
        "debut": debut,
        "fin": fin,
        "idx_harvest": idx_harvest,
        "idx_exit": idx_exit,
        "starts": starts,
    }


def test_le_vrai_demarrage_precede_le_exit_b():
    """Le chemin principal EST le superviseur harvest, puis on sort : l'ordre doit etre harvest -> exit."""
    a = _analyse()
    assert a["idx_harvest"] < a["idx_exit"], (
        "le demarrage reel (demarrer-tous harvest) doit PRECEDER le exit /b"
    )
    ligne_exit = a["lignes"][a["idx_exit"]].strip()
    assert ligne_exit.lower().startswith("exit /b"), ligne_exit


def test_le_bloc_legacy_est_documente_inatteignable():
    """Le bloc mort doit rester marque INATTEIGNABLE, entre le exit /b et les vieilles lignes start."""
    a = _analyse()
    lignes, idx_exit, fin, starts = a["lignes"], a["idx_exit"], a["fin"], a["starts"]
    marqueurs = [
        i for i in range(idx_exit + 1, fin)
        if "REFERENCE LEGACY CONSERVEE" in lignes[i] and "INATTEIGNABLE" in lignes[i]
    ]
    assert marqueurs, "le bloc legacy doit rester documente comme INATTEIGNABLE apres le exit /b"
    assert marqueurs[0] < starts[0], "le marqueur INATTEIGNABLE doit preceder les start morts"


def test_chaque_start_legacy_est_STRICTEMENT_apres_le_exit_b():
    """LE VERROU AUD-046 : toute ligne `start ...boucle_collecteur.cmd...` de la sous-routine est
    APRES le exit /b -> morte sur le chemin principal. Rougit si une legacy repasse avant."""
    a = _analyse()
    lignes, idx_exit, starts = a["lignes"], a["idx_exit"], a["starts"]
    assert starts, "aucune ligne legacy start trouvee : le test serait vacant"
    assert len(starts) >= len(LEGACY_CITES), (
        "trop peu de lignes legacy (%d) : ancrage suspect" % len(starts)
    )
    avant = [lignes[i].strip() for i in starts if i <= idx_exit]
    assert not avant, "des start collecteurs sont ATTEIGNABLES (avant/au exit /b): %r" % avant


@pytest.mark.parametrize("collecteur", LEGACY_CITES)
def test_les_collecteurs_legacy_cites_sont_bien_morts(collecteur):
    """Ancrage sur le VRAI texte : chaque collecteur cite par l'audit apparait comme ligne legacy
    `start ...` et se trouve APRES le exit /b (inatteignable)."""
    a = _analyse()
    lignes, idx_exit, starts = a["lignes"], a["idx_exit"], a["starts"]
    correspondances = [
        i for i in starts
        if (" %s " % collecteur) in (" " + lignes[i].strip() + " ")
    ]
    assert correspondances, (
        "ligne legacy `start %s` introuvable dans :demarrer_collecteurs" % collecteur
    )
    for i in correspondances:
        assert i > idx_exit, (
            "%s repasse AVANT le exit /b (redevenu atteignable): %r"
            % (collecteur, lignes[i].strip())
        )

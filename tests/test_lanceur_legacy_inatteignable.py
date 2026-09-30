"""AUD-046 — les anciens collecteurs ne peuvent jamais redevenir atteignables.

Un collecteur legacy peut rester comme référence APRES `exit /b`, ou être supprimé entièrement.
Le test ne force plus la conservation de code mort ; il interdit en revanche toute résurrection
avant la sortie de la sous-routine supervisée.
"""
from __future__ import annotations

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
LANCEUR = RACINE / "LANCER_HYPERSMART.cmd"
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
    s = ligne.strip()
    return s.startswith(":") and not s.startswith("::")


def _est_start_collecteur(ligne: str) -> bool:
    s = ligne.strip()
    return s.lower().startswith("start ") and "boucle_collecteur.cmd" in s


def _analyse() -> dict[str, object]:
    lignes = _lignes()
    debut = next(i for i, l in enumerate(lignes) if l.strip().lower() == ":demarrer_collecteurs")
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
    return {"lignes": lignes, "debut": debut, "fin": fin, "idx_harvest": idx_harvest,
            "idx_exit": idx_exit, "starts": starts}


def test_le_vrai_demarrage_precede_le_exit_b():
    a = _analyse()
    assert a["idx_harvest"] < a["idx_exit"]
    assert a["lignes"][a["idx_exit"]].strip().lower().startswith("exit /b")


def test_tout_start_legacy_restant_est_strictement_apres_exit():
    a = _analyse()
    lignes, idx_exit, starts = a["lignes"], a["idx_exit"], a["starts"]
    avant = [lignes[i].strip() for i in starts if i <= idx_exit]
    assert not avant, "des start collecteurs legacy sont atteignables: %r" % avant


def test_bloc_legacy_restant_est_documente_si_present():
    a = _analyse()
    lignes, idx_exit, fin, starts = a["lignes"], a["idx_exit"], a["fin"], a["starts"]
    if not starts:
        return
    marqueurs = [
        i for i in range(idx_exit + 1, fin)
        if "REFERENCE LEGACY CONSERVEE" in lignes[i] and "INATTEIGNABLE" in lignes[i]
    ]
    assert marqueurs
    assert marqueurs[0] < starts[0]


@pytest.mark.parametrize("collecteur", LEGACY_CITES)
def test_collecteur_legacy_est_absent_ou_mort(collecteur):
    """Suppression = mieux que code mort ; présence = obligatoirement après `exit /b`."""
    a = _analyse()
    lignes, idx_exit, starts = a["lignes"], a["idx_exit"], a["starts"]
    correspondances = [
        i for i in starts if (" %s " % collecteur) in (" " + lignes[i].strip() + " ")
    ]
    for i in correspondances:
        assert i > idx_exit, "%s est redevenu atteignable: %r" % (collecteur, lignes[i].strip())

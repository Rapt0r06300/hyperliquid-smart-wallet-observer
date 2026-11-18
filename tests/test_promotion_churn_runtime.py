"""La garde de promotion ignore le churn runtime, et seulement lui.

DEFAUT DU 18/11/2026. `POUSSER-GITHUB.cmd --promote-current-to-main` a rendu `NO_GO` avec
« des modifications suivies restent presentes apres le checkpoint ». Les deux seuls fichiers
modifies etaient `config/copy_vault_leaders_candidats.json` et
`config/leaders_actifs_classement.json` -- 478 insertions pour 478 suppressions, soit exactement
les memes lignes reecrites : un classement de leaders rafraichi par les collecteurs.

Or ces deux chemins sont DEJA declares dans `RUNTIME_CHURN_FILES`, avec un commentaire qui dit
pourquoi : « pour ne pas bloquer AlinaSync a chaque rafraichissement ». La garde de sync/pousse
consultait cette liste ; celle de promotion faisait un `if dirty:` sec. La promotion etait donc
impossible tant que la collecte tourne -- c'est-a-dire en exploitation normale.

Ces tests verifient les DEUX SENS, parce qu'un test qui ne verifie que le sens « ça passe » laisse
reintroduire le defaut par l'autre bout : du churn ne bloque pas, et un vrai fichier bloque.
"""
from __future__ import annotations

import pytest

from tools.alina_git_code_sync import (
    RUNTIME_CHURN_FILES,
    _can_defer_staged_protected,
)


def _classe(sortie_porcelain: str) -> tuple[list[str], list[str]]:
    """Reproduit le tri de la garde : (bloquants, churn).

    La garde lit `git status --porcelain=v1 -z --no-renames`, dont chaque entree est
    ``XY <chemin>`` terminee par un octet nul -- deux caracteres d'etat, une espace, le chemin.
    """
    bloquants: list[str] = []
    churn: list[str] = []
    for entree in sortie_porcelain.split("\0"):
        if len(entree) < 4:
            continue
        chemin = entree[3:].strip().replace("\\", "/")
        if not chemin:
            continue
        if chemin.casefold() in RUNTIME_CHURN_FILES or _can_defer_staged_protected(chemin):
            churn.append(chemin)
        else:
            bloquants.append(chemin)
    return bloquants, churn


def test_les_classements_de_leaders_sont_declares_comme_churn() -> None:
    """Les deux fichiers du refus reel sont bien connus comme du churn."""
    assert "config/copy_vault_leaders_candidats.json" in RUNTIME_CHURN_FILES
    assert "config/leaders_actifs_classement.json" in RUNTIME_CHURN_FILES


def test_la_source_des_lanes_reste_du_code_commitable() -> None:
    """`config/copy_vault_leaders.json` NE DOIT PAS etre du churn.

    Son commentaire d'origine l'exige : c'est la source des lanes, donc du code. L'ajouter a la
    liste ferait disparaitre silencieusement un vrai changement de configuration -- le defaut
    inverse de celui qu'on corrige, et le plus dangereux des deux.
    """
    assert "config/copy_vault_leaders.json" not in RUNTIME_CHURN_FILES


def test_du_churn_seul_ne_bloque_pas_la_promotion() -> None:
    sortie = (
        " M config/leaders_actifs_classement.json\0"
        " M config/copy_vault_leaders_candidats.json\0"
    )
    bloquants, churn = _classe(sortie)
    assert bloquants == [], "du churn runtime seul ne doit jamais bloquer la promotion"
    assert len(churn) == 2


@pytest.mark.parametrize(
    "chemin",
    [
        "src/hl_observer/contrat_paper.py",
        "config/copy_vault_leaders.json",      # la source des lanes : du CODE
        "tests/test_promotion_churn_runtime.py",
    ],
)
def test_un_vrai_fichier_bloque_toujours_la_promotion(chemin: str) -> None:
    """L'AUTRE SENS : la garde doit continuer de refuser ce qui n'est pas du churn.

    Sans ce test, on pourrait « reparer » le defaut en ignorant tout, ce qui promouvrait un arbre
    portant des modifications non commitees.
    """
    bloquants, _ = _classe(f" M {chemin}\0 M config/leaders_actifs_classement.json\0")
    assert bloquants == [chemin]


def test_la_casse_et_les_antislashs_ne_font_pas_passer_un_bloquant() -> None:
    """Le tri normalise la casse et les separateurs -- sous Windows git peut rendre les deux."""
    bloquants, churn = _classe(" M config\\Leaders_Actifs_Classement.json\0")
    assert bloquants == []
    assert churn == ["config/Leaders_Actifs_Classement.json"]


def test_une_sortie_vide_ou_tronquee_ne_leve_pas() -> None:
    """Un arbre propre rend une chaine vide ; une entree trop courte est ignoree, pas fatale."""
    assert _classe("") == ([], [])
    assert _classe("\0") == ([], [])
    assert _classe(" M\0") == ([], [])

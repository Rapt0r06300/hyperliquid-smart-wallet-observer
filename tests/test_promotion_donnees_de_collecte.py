"""Les données de collecte ne bloquent pas une publication de code — mais les secrets, si.

L'INTENTION EST ÉCRITE DANS LE MODULE, au-dessus de `DEFERRED_STAGED_PROTECTED_ROOTS` :

    « Data collectors may leave generated SAFE files staged while the operator is editing code.
      They stay outside code-only checkpoints, but their presence must not prevent an unrelated
      code publication. Secret-like files still fail closed through
      ``_can_defer_staged_protected`` below. »

Or la garde de promotion appelait `_pathspecs(include_protected=True)` : elle regardait donc
précisément les chemins que cette intention dit de tolérer. Mesure du 18/11/2026 : la collecte
avait réécrit **13 200 fichiers** de `catalog/` (13,4 M insertions, 16,1 M suppressions), et la
promotion refusait une publication de code qui n'avait aucun rapport avec eux.

La limite compte plus que la tolérance : un fichier qui ressemble à un secret doit échouer en
fermé, même sous un dossier de données. Publier un secret ne se répare pas.
"""
from __future__ import annotations

import pytest

from tools.alina_git_code_sync import (
    DEFERRED_STAGED_PROTECTED_ROOTS,
    RUNTIME_CHURN_FILES,
    _can_defer_staged_protected,
)

NUL = chr(0)


def _classe(sortie_porcelain: str) -> tuple[list[str], list[str]]:
    """Le même tri que la garde de promotion : (bloquants, churn)."""
    bloquants: list[str] = []
    churn: list[str] = []
    for entree in sortie_porcelain.split(NUL):
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


def _modifies(*chemins: str) -> str:
    return "".join(f" M {chemin}{NUL}" for chemin in chemins)


def test_les_recus_de_collecte_ne_bloquent_pas_la_promotion() -> None:
    """Les quatre familles vues dans le refus reel du 18/11/2026."""
    bloquants, churn = _classe(_modifies(
        "catalog/CAMPAIGN_RESILIENCE_RECEIPT.json",
        "catalog/receipts/market-e8-9-2026102920-v7-u0.json",
        "runtime/data/quelque_chose.jsonl",
        "logs/collecte.log",
    ))
    assert bloquants == [], f"des donnees de collecte bloquent encore : {bloquants}"
    assert len(churn) == 4


@pytest.mark.parametrize(
    "chemin",
    [
        "catalog/secrets/jeton.json",
        "catalog/credentials/compte.json",
        "data/private_key/cle.pem",
        "runtime/api_keys/cle.json",
    ],
)
def test_un_fichier_sensible_bloque_meme_sous_un_dossier_de_donnees(chemin: str) -> None:
    """ECHEC EN FERME pour ce qui ressemble a un secret.

    C'est la limite que pose `_can_defer_staged_protected`, et elle compte plus que la tolerance :
    une donnee de collecte republiee ne coute rien, un secret publie ne se repare pas.
    """
    bloquants, churn = _classe(_modifies(chemin))
    assert bloquants == [chemin], f"{chemin} doit bloquer : il a l'air d'un secret"
    assert churn == []


@pytest.mark.parametrize(
    "chemin",
    [
        "src/hl_observer/contrat_paper.py",
        "tests/test_promotion_donnees_de_collecte.py",
        "tools/alina_git_code_sync.py",
        "docs/CURRENT_STATE.md",
        "POUSSER-GITHUB.cmd",
    ],
)
def test_le_vrai_code_bloque_toujours(chemin: str) -> None:
    """L'AUTRE SENS, sans lequel on pourrait « reparer » la garde en ignorant tout.

    Une promotion doit refuser un arbre qui porte des modifications de CODE non commitees : c'est
    toute la raison d'etre de cette garde.
    """
    bloquants, _ = _classe(_modifies(chemin, "catalog/DATA_INDEX.json"))
    assert bloquants == [chemin]


def test_les_dossiers_tolere_sont_ceux_que_le_module_declare() -> None:
    """On ne tolere QUE ce que le module declare : aucune liste parallele.

    Si quelqu'un elargit `DEFERRED_STAGED_PROTECTED_ROOTS`, ce test ne s'y opposera pas -- mais la
    garde de promotion suivra automatiquement, puisqu'elle lit la meme source.
    """
    assert "catalog" in DEFERRED_STAGED_PROTECTED_ROOTS
    assert "runtime" in DEFERRED_STAGED_PROTECTED_ROOTS
    assert "src" not in DEFERRED_STAGED_PROTECTED_ROOTS
    assert "tests" not in DEFERRED_STAGED_PROTECTED_ROOTS
    assert "tools" not in DEFERRED_STAGED_PROTECTED_ROOTS

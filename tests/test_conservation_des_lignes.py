"""L'ÉQUATION DE CONSERVATION DES RUBANS : aucune ligne ne disparaît en silence.

Le 18/11/2026, un écart de 275 674 fills entre ce que le labo compte et ce que le ruban porte m'a
fait croire à une fuite. Les bilans publiés ont montré que le compte était exact à l'unité près —
mais rien, dans les tests, n'exigeait que ces égalités tiennent. Un futur changement qui perdrait
des lignes aurait donc pu passer sans rougir.

Les trois égalités, telles que mesurées sur le corpus réel :

    lignes_lues 12 297 560 − doublons_ecartes 3 543 350 = lignes_retenues  8 754 210
    retenues    8 754 210  − ecartees_par_le_filtre 289 959 = ecrites      8 464 251  (ruban direct)
    retenues    8 754 210  − ecartees_par_le_filtre 8 739 925 = ecrites       14 285  (historique)

Ces tests les exigent sur des cas synthétiques, pour chaque cible et quel que soit le filtre.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from hl_observer.backtesting import rubans_tri_externe as RT


def _lignes(nombre: int, *, doublons: int = 0):
    """`nombre` identités distinctes, plus `doublons` répétitions de la première."""
    base = [{"id": index, "v": index * 10} for index in range(nombre)]
    return base + [dict(base[0]) for _ in range(doublons)]


def _fabrique(lignes):
    return lambda: iter([dict(ligne) for ligne in lignes])


def _ecrire(tmp_path, lignes, cibles):
    """`cibles` : {nom: filtre}. Rend {nom: bilan}, car l'outil indexe ses bilans par `str(chemin)`."""
    bilans = RT.ecrire_rubans_tries(
        [(tmp_path / nom, filtre) for nom, filtre in cibles.items()],
        _fabrique(lignes),
        cle_identite=lambda ligne: (ligne["id"],),
        cle_tri=lambda ligne: (ligne["id"],),
    )
    return {pathlib.Path(chemin).name: bilan for chemin, bilan in bilans.items()}


def _verifier_conservation(bilan: dict) -> None:
    """Les deux égalités qui doivent tenir pour CHAQUE cible, sans exception."""
    assert bilan["lignes_lues"] - bilan["doublons_ecartes"] == bilan["lignes_retenues"], (
        "lues − doublons doit faire retenues : sinon des lignes disparaissent entre la lecture "
        "et la déduplication"
    )
    assert bilan["lignes_retenues"] - bilan["ecartees_par_le_filtre"] == bilan["lignes_ecrites"], (
        "retenues − écartées doit faire écrites : sinon des lignes disparaissent à l'écriture"
    )


def test_conservation_SANS_filtre(tmp_path):
    bilan = _ecrire(tmp_path, _lignes(20), {"tout.jsonl": None})["tout.jsonl"]
    _verifier_conservation(bilan)
    assert bilan["lignes_ecrites"] == 20 and bilan["ecartees_par_le_filtre"] == 0


def test_conservation_AVEC_doublons(tmp_path):
    bilan = _ecrire(tmp_path, _lignes(10, doublons=7), {"tout.jsonl": None})["tout.jsonl"]
    _verifier_conservation(bilan)
    assert bilan["lignes_lues"] == 17 and bilan["doublons_ecartes"] == 7
    assert bilan["lignes_ecrites"] == 10


def test_conservation_AVEC_un_filtre_partiel(tmp_path):
    bilan = _ecrire(
        tmp_path, _lignes(20), {"pairs.jsonl": lambda ligne: ligne["id"] % 2 == 0},
    )["pairs.jsonl"]
    _verifier_conservation(bilan)
    assert bilan["lignes_ecrites"] == 10 and bilan["ecartees_par_le_filtre"] == 10


def test_conservation_quand_le_filtre_REFUSE_TOUT(tmp_path):
    """Le cas du ruban BBO vidé : un ruban vide doit le dire par ses compteurs."""
    bilan = _ecrire(tmp_path, _lignes(12), {"rien.jsonl": lambda _ligne: False})["rien.jsonl"]
    _verifier_conservation(bilan)
    assert bilan["lignes_ecrites"] == 0 and bilan["ecartees_par_le_filtre"] == 12
    assert (tmp_path / "rien.jsonl").read_bytes() == b""


def test_conservation_sur_CHAQUE_cible_d_une_meme_passe(tmp_path):
    """La forme réelle : deux rubans écrits en une passe, chacun avec son filtre.

    C'est exactement la configuration du corpus — un ruban direct et un ruban historique tirés des
    mêmes lignes — et chaque bilan doit boucler indépendamment.
    """
    bilans = _ecrire(tmp_path, _lignes(30, doublons=5), {
        "direct.jsonl": lambda ligne: ligne["id"] >= 10,
        "historique.jsonl": lambda ligne: ligne["id"] < 10,
        "tout.jsonl": None,
    })
    assert len(bilans) == 3
    for chemin, bilan in bilans.items():
        _verifier_conservation(bilan)
        assert bilan["lignes_retenues"] == 30, chemin
        assert bilan["doublons_ecartes"] == 5, chemin
    noms = {nom: bilan["lignes_ecrites"] for nom, bilan in bilans.items()}
    assert noms == {"direct.jsonl": 20, "historique.jsonl": 10, "tout.jsonl": 30}
    # Les deux filtres sont complémentaires : leurs écritures reconstituent le total.
    assert noms["direct.jsonl"] + noms["historique.jsonl"] == noms["tout.jsonl"]


def test_les_lignes_ECRITES_sont_bien_celles_annoncees(tmp_path):
    """Un compteur juste sur un fichier faux ne vaudrait rien : on compte le fichier aussi."""
    bilan = _ecrire(tmp_path, _lignes(25, doublons=3),
                    {"pairs.jsonl": lambda ligne: ligne["id"] % 2 == 0})["pairs.jsonl"]
    chemin = tmp_path / "pairs.jsonl"
    reelles = [json.loads(ligne) for ligne in chemin.read_text(encoding="utf-8").splitlines()]
    assert len(reelles) == bilan["lignes_ecrites"]
    assert {ligne["id"] for ligne in reelles} == {index for index in range(25) if index % 2 == 0}


@pytest.mark.parametrize("identites,doublons", ((1, 0), (1, 9), (100, 0), (100, 50)))
def test_la_conservation_tient_a_toutes_les_echelles(tmp_path, identites, doublons):
    bilans = _ecrire(tmp_path, _lignes(identites, doublons=doublons),
                     {"a.jsonl": lambda ligne: ligne["id"] % 3 != 0, "b.jsonl": None})
    for bilan in bilans.values():
        _verifier_conservation(bilan)


def test_un_ruban_LOURD_du_labo_respecte_aussi_la_conservation(tmp_path):
    """Le contrôle sur les vraies clés du Copy-Vault, pas seulement sur une fixture abstraite."""
    from hl_observer.backtesting import copy_vault_rubans_lourds as RL

    fills = [
        {"ts_ms": 1_000, "vault": "0xA", "tid": "1", "isSnapshot": False, "source": "LIVE_WS"},
        {"ts_ms": 2_000, "vault": "0xA", "tid": "2", "isSnapshot": True, "source": "REST"},
        {"ts_ms": 3_000, "vault": "0xB", "tid": "3", "isSnapshot": False, "source": "INCONNU"},
        {"ts_ms": 1_000, "vault": "0xA", "tid": "1", "isSnapshot": False, "source": "LIVE_WS"},
    ]
    brut = RT.ecrire_rubans_tries(
        [
            (tmp_path / "direct.jsonl", RL.est_un_fill_direct_causal),
            (tmp_path / "histo.jsonl", RL.est_un_fill_historique),
        ],
        lambda: iter([dict(f) for f in fills]),
        cle_identite=RL.identite_fill,
        cle_tri=RL.tri_fill,
    )
    bilans = {pathlib.Path(chemin).name: bilan for chemin, bilan in brut.items()}
    for bilan in bilans.values():
        _verifier_conservation(bilan)
        assert bilan["lignes_lues"] == 4 and bilan["doublons_ecartes"] == 1
    assert bilans["direct.jsonl"]["lignes_ecrites"] == 1, "seul le LIVE_WS est causal"
    assert bilans["histo.jsonl"]["lignes_ecrites"] == 1, "seul le snapshot est historique"
    # Le fill de source INCONNUE n'est dans aucun ruban — mais il est COMPTÉ par les deux filtres.
    assert bilans["direct.jsonl"]["ecartees_par_le_filtre"] == 2
def test_le_CONTROLE_LUI_MEME_rejette_un_bilan_incoherent():
    """Un contrôle qui ne peut pas échouer n'en est pas un.

    On lui donne des bilans faux dans les deux sens pour prouver qu'il les voit : des lignes
    perdues entre la lecture et la déduplication, puis entre la déduplication et l'écriture.
    """
    sain = {"lignes_lues": 10, "doublons_ecartes": 2, "lignes_retenues": 8,
            "ecartees_par_le_filtre": 3, "lignes_ecrites": 5}
    _verifier_conservation(sain)

    perdu_a_la_deduplication = {**sain, "lignes_retenues": 7, "ecartees_par_le_filtre": 2}
    with pytest.raises(AssertionError, match="lues"):
        _verifier_conservation(perdu_a_la_deduplication)

    perdu_a_l_ecriture = {**sain, "lignes_ecrites": 4}
    with pytest.raises(AssertionError, match="retenues"):
        _verifier_conservation(perdu_a_l_ecriture)

    invente_a_l_ecriture = {**sain, "lignes_ecrites": 6}
    with pytest.raises(AssertionError, match="retenues"):
        _verifier_conservation(invente_a_l_ecriture)


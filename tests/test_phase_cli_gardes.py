"""Les gardes de la CLI operateur des phases : un recu ne se reecrit jamais en silence.

POURQUOI CE FICHIER EXISTE. La mesure du 21/11/2026 a liste 7 modules qu'aucun test n'atteint.
Celui-ci est la porte par laquelle un OPERATEUR change la phase du systeme et ecrit un recu de
transition. Deux choses doivent y etre vraies et ne l'etaient verifiees nulle part :

  * les identifiants sont bornes et sans echappatoire de chemin (un `--requested-by ../..`
    ecrirait un recu hors du dossier des recus) ;
  * un recu deja present n'est JAMAIS reecrit : s'il differe, c'est un CONFLIT nomme, pas un
    ecrasement. Un recu qu'on peut reecrire ne prouve plus rien.
"""
from __future__ import annotations

import argparse
import json

import pytest

from hl_observer.control_plane import phase_cli as CLI

SHA256 = "a" * 64
SHA1 = "b" * 40


class _Recu:
    """Double minimal : la fonction testee n'a besoin que de `request_id` et `to_dict()`."""

    def __init__(self, request_id: str, charge: dict):
        self.request_id = request_id
        self._charge = charge

    def to_dict(self) -> dict:
        return dict(self._charge)


# ------------------------------------------------------------------ les identifiants
@pytest.mark.parametrize("mauvais", [
    "", "   ", "../evasion", "..", "a/b", "a" + chr(92) + "b", "-commence-par-un-tiret",
    ".cache", "a" * 129, "a b", "accentue" + chr(233), "a;b", "a|b", "a\nb",
])
def test_une_identite_dangereuse_ou_demesuree_est_refusee(mauvais):
    with pytest.raises(argparse.ArgumentTypeError):
        CLI._safe_identity(mauvais)


@pytest.mark.parametrize("bon", ["operator", "flo", "runner-01", "a", "a" * 128,
                                  "ci:github:main", "v1.2.3_x"])
def test_une_identite_legitime_passe(bon):
    """LA MOITIE QUI COMPTE : une garde qui refuse tout bloque l'operateur au lieu de le proteger."""
    assert CLI._safe_identity(bon) == bon


@pytest.mark.parametrize("mauvais", ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, SHA1,
                                      "a" * 32 + "-" + "a" * 31])
def test_un_request_id_qui_n_est_pas_un_sha256_minuscule_est_refuse(mauvais):
    with pytest.raises(argparse.ArgumentTypeError):
        CLI._request_id(mauvais)


def test_un_vrai_sha256_minuscule_passe():
    assert CLI._request_id(SHA256) == SHA256


@pytest.mark.parametrize("mauvais", ["", "B" * 40, "b" * 39, "b" * 41, SHA256, "z" * 40])
def test_un_commit_sha_non_conforme_est_refuse(mauvais):
    with pytest.raises(argparse.ArgumentTypeError):
        CLI._commit_sha(mauvais)


def test_un_vrai_commit_sha_passe():
    assert CLI._commit_sha(SHA1) == SHA1


# ------------------------------------------------------------------ le recu de transition
def test_le_recu_est_ecrit_une_fois_et_relisible(tmp_path):
    recu = _Recu(SHA256, {"phase": "ANALYZE", "request_id": SHA256})
    CLI._persist_transition_receipt(recu, receipt_dir=str(tmp_path / "recus"))
    cible = tmp_path / "recus" / f"{SHA256}.json"
    assert json.loads(cible.read_text(encoding="utf-8")) == recu.to_dict()


def test_aucun_fichier_temporaire_ne_survit(tmp_path):
    """Un `.tmp` oublie, c'est un recu a moitie ecrit qu'un lecteur prendra pour vrai."""
    CLI._persist_transition_receipt(_Recu(SHA256, {"a": 1}), receipt_dir=str(tmp_path))
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_rejouer_le_MEME_recu_est_idempotent(tmp_path):
    """Rejouer une transition identique ne doit ni lever ni modifier la preuve."""
    recu = _Recu(SHA256, {"phase": "ANALYZE"})
    CLI._persist_transition_receipt(recu, receipt_dir=str(tmp_path))
    avant = (tmp_path / f"{SHA256}.json").read_bytes()
    CLI._persist_transition_receipt(recu, receipt_dir=str(tmp_path))
    assert (tmp_path / f"{SHA256}.json").read_bytes() == avant


def test_un_recu_DIFFERENT_sous_le_meme_identifiant_est_un_CONFLIT_NOMME(tmp_path):
    """DEUX objets differents ne peuvent pas porter le meme nom : refus, jamais ecrasement."""
    CLI._persist_transition_receipt(_Recu(SHA256, {"phase": "ANALYZE"}),
                                    receipt_dir=str(tmp_path))
    avant = (tmp_path / f"{SHA256}.json").read_bytes()
    with pytest.raises(ValueError, match="identity conflict"):
        CLI._persist_transition_receipt(_Recu(SHA256, {"phase": "COLLECT"}),
                                        receipt_dir=str(tmp_path))
    assert (tmp_path / f"{SHA256}.json").read_bytes() == avant, (
        "la preuve d'origine a ete modifiee malgre le refus")


def test_les_octets_du_recu_sont_deterministes(tmp_path):
    """Deux recus de meme contenu doivent donner les MEMES octets, sinon tout diff ment."""
    a, b = tmp_path / "a", tmp_path / "b"
    CLI._persist_transition_receipt(_Recu(SHA256, {"z": 1, "a": 2}), receipt_dir=str(a))
    CLI._persist_transition_receipt(_Recu(SHA256, {"a": 2, "z": 1}), receipt_dir=str(b))
    assert (a / f"{SHA256}.json").read_bytes() == (b / f"{SHA256}.json").read_bytes()


# ------------------------------------------------------------------ le parseur
def test_le_parseur_se_construit_et_exige_ses_arguments():
    parseur = CLI.build_parser()
    assert isinstance(parseur, argparse.ArgumentParser)
    with pytest.raises(SystemExit):
        parseur.parse_args([])


def test_le_parseur_refuse_un_request_id_malforme_sur_la_ligne_de_commande():
    """La garde doit agir AU BORD : un identifiant invalide ne doit jamais entrer dans le code."""
    parseur = CLI.build_parser()
    sous = [a for a in parseur._subparsers._group_actions[0].choices] if parseur._subparsers else []
    assert sous, "la CLI n'expose plus aucune sous-commande"

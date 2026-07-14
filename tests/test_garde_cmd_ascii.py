"""UN .cmd NON-ASCII NE DOIT PLUS JAMAIS PASSER (2026-07-12).

CE BUG EST REVENU TROIS FOIS
----------------------------
  1. MOISSONNER-GITHUB.cmd -> "'ISSONNEUR' n'est pas reconnu"
  2. MOISSONNER-GITHUB.cmd -> cmd.exe EXECUTAIT les commentaires REM
  3. MEGATEST.cmd          -> "'5001' n'est pas reconnu" en boucle
                              ("chcp 65001" ampute de son 6 par le decalage d'analyseur)

Trois fois le meme bug, corrige a la main trois fois. Ca s'arrete ici.

CE QUE CES TESTS DEFENDENT
--------------------------
1. Le garde DETECTE le combo mortel (non-ASCII + chcp).
2. Il ne CRIE PAS sur un fichier propre.
3. MEGATEST.cmd -- le fichier qui autorise les commits -- est en ASCII PUR.

Aucun reseau, aucun ordre : lecture de fichiers uniquement.
"""
from __future__ import annotations

from pathlib import Path

from tools.garde_cmd_ascii import scanner_cmd

RACINE = Path(__file__).resolve().parents[1]


def test_le_garde_attrape_le_combo_mortel_non_ascii_plus_chcp(tmp_path) -> None:
    """LE test du bug : un tiret cadratin + chcp = cmd execute ses commentaires."""
    piege = tmp_path / "PIEGE.cmd"
    piege.write_bytes(
        b"@echo off\r\n"
        b"chcp 65001 >nul\r\n"
        b"REM   MEGATEST \xe2\x80\x94 LES 7 CONTROLES\r\n"   # tiret cadratin
        b"echo bonjour\r\n"
    )
    rap = scanner_cmd(tmp_path)

    assert rap["verdict"] == "ECHEC", (
        "REGRESSION : le garde n'a pas vu un .cmd avec un octet non-ASCII ET un chcp. "
        "C'est EXACTEMENT ce qui a produit \"'5001' n'est pas reconnu\" en boucle : "
        "cmd.exe decale son analyseur, perd le 6 de 65001, et tente d'executer 5001."
    )
    assert len(rap["casses"]) == 1
    assert rap["casses"][0]["fichier"] == "PIEGE.cmd"
    assert "—" in rap["casses"][0]["exemples"][0]["caracteres"], (
        "le garde doit NOMMER le caractere fautif -- sinon on cherche a l'aveugle"
    )


def test_un_cmd_ascii_pur_ne_declenche_rien(tmp_path) -> None:
    """Le garde ne doit pas devenir un mur : un fichier propre passe."""
    (tmp_path / "PROPRE.cmd").write_bytes(
        b"@echo off\r\nsetlocal\r\nREM   MEGATEST - LES 7 CONTROLES\r\npython x.py\r\n"
    )
    rap = scanner_cmd(tmp_path)
    assert rap["verdict"] == "OK"
    assert rap["casses"] == []
    assert "PROPRE.cmd" in rap["propres"]


def test_non_ascii_SANS_chcp_est_signale_mais_PAS_bloquant(tmp_path) -> None:
    """Sans chcp, un non-ASCII n'affiche qu'un mojibake. Moche, pas fatal.

    On le SIGNALE (il faut le nettoyer), mais on ne bloque pas un commit pour ca --
    sinon le garde deviendrait un obstacle, et on finirait par le desactiver.
    """
    (tmp_path / "MOCHE.cmd").write_bytes(b"@echo off\r\nREM   accent : \xc3\xa9\r\n")
    rap = scanner_cmd(tmp_path)
    assert rap["verdict"] == "OK", "pas de chcp -> pas bloquant"
    assert len(rap["a_risque"]) == 1
    assert rap["a_risque"][0]["fichier"] == "MOCHE.cmd"


def test_une_mention_de_chcp_dans_un_REM_ne_compte_PAS_comme_un_chcp_actif(tmp_path) -> None:
    """Le garde doit distinguer un chcp EXECUTE d'un chcp CITE dans un commentaire.

    Sinon MEGATEST.cmd -- qui EXPLIQUE le bug dans ses commentaires -- serait
    faussement accuse. Un garde qui produit des faux positifs finit desactive.
    """
    (tmp_path / "EXPLIQUE.cmd").write_bytes(
        b"@echo off\r\n"
        b"REM   pas de chcp ici : c'est justement le bug\r\n"
        b"REM   accent volontaire : \xc3\xa9\r\n"
        b"python x.py\r\n"
    )
    rap = scanner_cmd(tmp_path)
    assert rap["verdict"] == "OK", (
        "un `chcp` cite dans un REM n'est PAS execute -- le garde ne doit pas s'y tromper"
    )
    assert len(rap["a_risque"]) == 1


def test_MEGATEST_cmd_le_fichier_qui_autorise_les_commits_est_en_ASCII_PUR() -> None:
    """Le fichier le plus important du projet ne doit PAS pouvoir s'auto-saboter."""
    megatest = RACINE / "MEGATEST.cmd"
    if not megatest.exists():  # pragma: no cover
        return
    octets = megatest.read_bytes()
    fautifs = sorted({b for b in octets if b > 0x7F})
    assert not fautifs, (
        f"MEGATEST.cmd contient {len(fautifs)} octet(s) non-ASCII : {fautifs!r}. "
        "C'est LE fichier qui autorise les commits. S'il se sabote lui-meme, plus rien "
        "n'est verifie -- et on commiterait du code casse en croyant l'avoir teste."
    )

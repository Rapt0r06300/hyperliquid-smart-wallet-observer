"""GH-01 -- L'INVARIANT SUR LES INTERRUPTEURS. Celui qui manquait depuis le debut.

T3b a cree l'invariant sur les MODULES. Il a marche : il a trouve 4 garde-fous que mon grep
avait rates. Mais un module peut etre **parfaitement branche, teste, joignable** -- et ne jamais
s'executer parce que son flag vaut "0" et que personne ne l'a jamais pose.

L'audit de cablage ne voit RIEN : l'import existe, l'appel existe. Seule la VALEUR du flag
decide, et elle est invisible au code.

    >>> UN INTERRUPTEUR NI ALLUME NI DECLARE ETEINT FAIT ECHOUER CETTE SUITE. <<<

C'est l'invariant. Il se verifie a CHAQUE execution, contrairement a un inventaire -- qui se
fait une fois et se trompe.

Aucun ordre reel.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from hl_observer.risk.interrupteurs import (
    ALLUME,
    DECISIONS,
    ETEINT_PAR_OUBLI,
    ETEINT_VOLONTAIREMENT,
    PAQUETS_SURVEILLES,
    PAR_FLAG,
    REGISTRE,
    a_allumer,
    eteints_volontairement,
)

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src" / "hl_observer"

_MASTER = re.compile(r'^\s*MASTER_FLAG\s*=\s*["\']([A-Z0-9_]+)["\']', re.M)


def _flags_du_code() -> dict[str, str]:
    """{flag: module} -- DECOUVERTS dans le code, jamais ecrits a la main.

    Une liste ecrite a la main expire le jour ou quelqu'un ajoute un flag, et personne ne se
    plaint. C'est exactement le piege qu'on essaie de fermer.
    """
    out: dict[str, str] = {}
    for paquet in PAQUETS_SURVEILLES:
        d = SRC / paquet
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            try:
                texte = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for flag in _MASTER.findall(texte):
                out[flag] = f"{paquet}.{f.stem}"
    return out


def _texte_des_lanceurs() -> str:
    morceaux = []
    for motif in ("*.cmd", "*.ps1", "tools/*.ps1", "tools/*.cmd"):
        for f in RACINE.glob(motif):
            try:
                morceaux.append(f.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return "\n".join(morceaux)


# ====================================================== L'INVARIANT


def test_TOUT_master_flag_du_code_est_DECLARE_au_registre():
    """🔴 L'INVARIANT. Un interrupteur non declare est un interrupteur qu'on OUBLIERA.

    C'est ce qui est arrive a la pile V26 ENTIERE : 5 flags, codes, testes, branches --
    et AUCUN dans un lanceur. Personne ne s'en est plaint pendant des semaines, parce que
    rien ne le VERIFIAIT.
    """
    du_code = _flags_du_code()
    manquants = sorted(set(du_code) - set(PAR_FLAG))
    assert not manquants, (
        "MASTER_FLAG(s) presents dans le code mais ABSENTS du registre "
        "`risk/interrupteurs.py` :\n  "
        + "\n  ".join(f"{f}  ({du_code[f]})" for f in manquants)
        + "\n\nChaque interrupteur doit porter une DECISION explicite : ALLUME (et le lanceur "
          "le pose) ou ETEINT_VOLONTAIREMENT (et on ecrit POURQUOI). Il n'y a pas de 3e option."
    )


def test_aucun_flag_FANTOME_au_registre():
    """L'inverse : un registre qui declare des flags disparus du code ment aussi."""
    du_code = _flags_du_code()
    fantomes = sorted(set(PAR_FLAG) - set(du_code))
    assert not fantomes, (
        "le registre declare des interrupteurs qui n'existent PLUS dans le code : "
        f"{fantomes}. Un registre perime est pire qu'aucun registre : il rassure a tort."
    )


def test_ETEINT_PAR_OUBLI_est_BANNI():
    """Cette valeur existe UNIQUEMENT pour etre interdite. On decide, ou on assume.

    « Eteint par oubli » n'est pas une decision -- c'est l'aveu qu'on n'en a pas pris.
    """
    coupables = [i.flag for i in REGISTRE if i.decision == ETEINT_PAR_OUBLI]
    assert not coupables, (
        f"{coupables} sont declares ETEINT_PAR_OUBLI. Ce n'est pas une decision, c'est un aveu. "
        "Allumez-les, ou ecrivez pourquoi vous ne le faites pas."
    )


def test_toute_decision_est_dans_le_vocabulaire():
    for i in REGISTRE:
        assert i.decision in DECISIONS, f"{i.flag} : decision inconnue « {i.decision} »"


def test_un_ETEINT_VOLONTAIRE_doit_porter_un_VRAI_motif():
    """Un motif de trois mots n'est pas un motif -- c'est une excuse.

    Le motif doit expliquer POURQUOI, pas repeter QUOI. On exige de la substance : sans elle,
    dans six mois, personne ne saura si l'extinction etait un choix ou un oubli deguise.
    """
    for f in eteints_volontairement():
        i = PAR_FLAG[f]
        assert len(i.motif) >= 120, (
            f"{f} : motif trop court ({len(i.motif)} car.). Un interrupteur eteint DOIT porter "
            "un raisonnement qui tienne dans six mois, pas un slogan."
        )


# ====================================================== LE LANCEUR TIENT-IL PAROLE ?


def test_tout_flag_dit_ALLUME_est_VRAIMENT_pose_par_un_lanceur():
    """🔴 LE test qui aurait attrape la pile V26.

    Se declarer « ALLUME » dans un registre ne pose aucun flag. Il faut que le LANCEUR -- la
    seule source de verite du runtime (cf. audit du 11/07 : le .ps1 ecrase le .cmd) -- le pose
    vraiment. Sinon on a juste ecrit une intention.
    """
    lanceurs = _texte_des_lanceurs()
    assert lanceurs, "aucun lanceur lu : le test tournerait a vide et ne prouverait rien"

    absents = [f for f in a_allumer() if f not in lanceurs]
    assert not absents, (
        "Interrupteur(s) declares ALLUME mais ABSENTS de tout lanceur :\n  "
        + "\n  ".join(absents)
        + "\n\nLe registre dit une chose, le runtime en fait une autre. C'est exactement la "
          "maladie qu'on soigne : la capacite est presente, l'interrupteur est eteint, et rien "
          "ne se plaint."
    )


def test_un_flag_ETEINT_VOLONTAIREMENT_n_est_PAS_pose_par_accident():
    """La symetrie. Si on a decide de l'eteindre, le lanceur ne doit pas l'allumer en douce."""
    lanceurs = _texte_des_lanceurs()
    for f in eteints_volontairement():
        # On cherche une affectation a une valeur VRAIE (=1, ="1", :true...). La simple mention
        # du nom (dans un commentaire, par ex.) est autorisee.
        allume = re.search(rf'{re.escape(f)}\s*=\s*["\']?\s*(1|true|yes|on)\b', lanceurs, re.I)
        assert not allume, (
            f"{f} est declare ETEINT_VOLONTAIREMENT au registre, mais un lanceur l'ALLUME. "
            "Le registre et le runtime se contredisent -- l'un des deux ment."
        )


# ====================================================== LE CONTENU DES DECISIONS


def test_les_protections_GH01_sont_bien_ALLUMEES():
    """GH-01 demandait `global_stop` + `stop_per_pair`. Les deux sont dans protections_v26
    (StoplossGuard, avec `SG_PER_MARKET`). Le code existait DEJA -- il n'etait pas allume."""
    assert PAR_FLAG["HYPERSMART_V26_PROTECTIONS"].decision == ALLUME
    assert PAR_FLAG["HYPERSMART_V26_GRADED_HALT"].decision == ALLUME


def test_KELLY_reste_ETEINT_et_le_motif_dit_POURQUOI():
    """Il change la TAILLE, donc le PnL. Et Kelly sur un edge NUL (mesure par Q1/Q3) ne dit
    rien de sensé. On ne l'allume pas « pour voir »."""
    i = PAR_FLAG["HYPERSMART_V26_KELLY_LEADER"]
    assert i.decision == ETEINT_VOLONTAIREMENT
    assert "TAILLE" in i.motif.upper()
    assert "edge" in i.motif.lower()


def test_la_regle_de_decision_est_TENUE_partout():
    """Le registre s'impose une regle : un interrupteur qui ne fait que REFUSER doit etre ALLUME.

    Ce test verifie qu'on ne l'a pas oubliee en route -- car une regle qu'on n'applique qu'une
    fois sur deux n'est pas une regle, c'est une preference.
    """
    for i in REGISTRE:
        if i.decision != ALLUME:
            continue
        # un garde-fou (qui refuse) ne doit pas toucher a la taille
        assert "taille" not in i.role.lower(), (
            f"{i.flag} est ALLUME mais son role mentionne la TAILLE : il change le PnL, "
            "il ne devrait pas etre allume sans mesure prealable."
        )

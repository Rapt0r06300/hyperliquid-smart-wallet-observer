"""C86 — un fill PASSIF du leader ne porte presque pas d'information : en faire un CRITÈRE.

`taker_notional_share` (part du notionnel exécutée en taker) était déjà **calculée** par
`copy_vault_copiability_mesures` puis simplement recopiée plus loin — jamais utilisée pour DÉCIDER.
C'est exactement le travers que ce projet traque : « MENTION ≠ PORTE ». Une mesure qui n'entre dans
aucune décision ne sert à rien.

Pourquoi le critère est fondé : un fill passif a été rempli parce que le marché est venu le chercher,
pas parce que le leader voulait entrer MAINTENANT. Il n'exprime donc aucune urgence, ne porte presque
pas d'information directionnelle, et le copier paye le spread et les frais sans acheter de dérive
(mesure du projet : 67 % des fills sont passifs et valent ~0 avant frais).

Ces tests verrouillent surtout les deux subtilités qui comptent :

* « part inconnue » n'est PAS « part nulle » — sinon on écarterait des leaders faute de données ;
* le filtre suit la convention FAIL-OPEN du module (comme `copie_leader_faible`) : on ne bloque
  jamais sur une absence d'information, et il est INACTIF par défaut.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import leader_quality_signal as Q  # noqa: E402

A, B, C = "0xA", "0xB", "0xC"


# ------------------------------------------------------------------ lecture de la mesure

def test_la_part_agressive_est_lue_par_leader():
    parts = Q.part_agressive_par_leader([
        {"unit": A, "taker_notional_share": 0.9},
        {"unit": B, "taker_notional_share": 0.2},
    ])
    assert parts == {A: 0.9, B: 0.2}


def test_les_deux_noms_de_cle_du_leader_sont_acceptes():
    """Les mesures parlent de `unit`, d'autres tables de `vault` : les deux doivent marcher."""
    parts = Q.part_agressive_par_leader([{"vault": A, "taker_notional_share": 0.7}])
    assert parts == {A: 0.7}


def test_une_part_INCONNUE_reste_None_et_ne_devient_JAMAIS_zero():
    """LA subtilite : « on ne sait pas » et « il n'etait jamais agressif » sont deux choses tres
    differentes. Confondre les deux ecarterait des leaders faute de donnees, pas faute de qualite."""
    parts = Q.part_agressive_par_leader([
        {"unit": A, "taker_notional_share": None},
        {"unit": B, "taker_notional_share": float("nan")},
        {"unit": C, "taker_notional_share": "0,9"},
    ])
    assert parts == {A: None, B: None, C: None}
    assert parts[A] is not 0.0 and parts[A] != 0.0          # noqa: F632 — l'intention est explicite


def test_les_lignes_inutilisables_sont_ignorees():
    parts = Q.part_agressive_par_leader([
        None, "pas un dict", {}, {"taker_notional_share": 0.9},   # sans nom de leader
        {"unit": A, "taker_notional_share": 0.8},
    ])
    assert parts == {A: 0.8}


def test_une_entree_vide_ne_fait_rien_planter():
    assert Q.part_agressive_par_leader(None) == {}
    assert Q.part_agressive_par_leader([]) == {}


# ------------------------------------------------------------------ le filtre décide

def test_un_leader_majoritairement_passif_est_ecarte():
    parts = {A: 0.9, B: 0.2}
    assert Q.copie_leader_trop_passif(parts, B, seuil=0.5) is True
    assert Q.copie_leader_trop_passif(parts, A, seuil=0.5) is False


def test_le_seuil_est_strict():
    """Pile au seuil, on ne jette pas : le doute profite au leader (comme le filtre de track-record)."""
    assert Q.copie_leader_trop_passif({A: 0.5}, A, seuil=0.5) is False
    assert Q.copie_leader_trop_passif({A: 0.4999}, A, seuil=0.5) is True


def test_une_part_inconnue_ne_bloque_JAMAIS():
    """FAIL-OPEN, convention du module : on ne bloque pas sur une absence d'information."""
    assert Q.copie_leader_trop_passif({A: None}, A, seuil=0.9) is False


def test_un_leader_absent_de_la_mesure_ne_bloque_pas_non_plus():
    assert Q.copie_leader_trop_passif({A: 0.9}, "0xINCONNU", seuil=0.9) is False
    assert Q.copie_leader_trop_passif({}, None, seuil=0.9) is False


def test_le_filtre_est_INACTIF_par_defaut():
    """Un filtre nouvellement ajoute ne doit rien changer tant qu'on ne l'active pas explicitement."""
    parts = {A: 0.0, B: 0.01, C: 1.0}
    for vault in (A, B, C):
        assert Q.copie_leader_trop_passif(parts, vault, seuil=Q.SEUIL_PART_AGRESSIVE_OFF) is False


# ------------------------------------------------------------------ cohérence du module

def test_la_convention_FAIL_OPEN_est_la_MEME_que_le_filtre_de_track_record():
    """Deux filtres du meme module qui traiteraient l'information manquante differemment seraient un
    piege a bug. On verifie que les deux renvoient False quand on ne sait pas."""
    assert Q.copie_leader_faible({}, A, 1_000, seuil_usd=0.0) is False      # pas d'historique
    assert Q.copie_leader_trop_passif({}, A, seuil=0.9) is False            # pas de part connue


def test_CANARI_la_part_est_LUE_et_non_RECALCULEE():
    """Recalculer la part ici divergerait de `copy_vault_copiability_mesures` le jour ou sa definition
    change (notionnel crossed==1 / notionnel total). On exige la lecture de la cle, pas un calcul."""
    import ast
    import textwrap

    src = inspect.getsource(Q.part_agressive_par_leader)
    assert "taker_notional_share" in src
    # On n'examine que le CORPS DE CODE : la docstring a le droit (et le devoir) d'expliquer que la
    # part vaut « notionnel crossed == 1 / notionnel total ». Confondre l'explication avec le calcul
    # serait un canari qui interdit de documenter — exactement le contraire du but.
    fonction = ast.parse(textwrap.dedent(src)).body[0]
    corps = fonction.body[1:] if ast.get_docstring(fonction) else fonction.body
    code = chr(10).join(ast.unparse(noeud) for noeud in corps)
    for interdit in ("crossed", "sum(", "/ notional", "notional /"):
        assert interdit not in code, f"la part ne doit pas etre recalculee ici ({interdit})"


def test_les_deux_filtres_sont_exportes():
    for nom in ("part_agressive_par_leader", "copie_leader_trop_passif", "SEUIL_PART_AGRESSIVE_OFF"):
        assert nom in Q.__all__

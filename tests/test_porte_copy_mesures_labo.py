"""Verrous du moteur PAPER issus des MESURES du labo (étude de copiabilité).

Ces verrous ne peuvent que restreindre : ils refusent un leader mesuré non copiable et un
faux consensus formé de clones d'un même opérateur. Leur absence n'ouvre jamais rien.
"""
from __future__ import annotations

import json

from hl_observer.signals.porte_copy_whitelist import (
    CHEMIN_PLAN_LABO,
    MOTIF_CONSENSUS_CLONES,
    MOTIF_HORS_LISTE,
    MOTIF_NON_COPIABLE_LABO,
    charger_classes_labo,
    signal_copy_autorise,
)
from tests.test_porte_copy_whitelist import _ecrire

LENT, AUTRE, ROBOT, CLONE = "0xaaa1", "0xaaa2", "0xbbb1", "0xbbb2"


def _plan(root, leaders):
    chemin = root / CHEMIN_PLAN_LABO
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"leaders": leaders}), encoding="utf-8")


def _whitelist(root, adresses):
    _ecrire(root, [{"adresse": a} for a in adresses])


def test_sans_plan_du_labo_la_porte_garde_exactement_son_comportement(tmp_path):
    _whitelist(tmp_path, [LENT, AUTRE])
    assert charger_classes_labo(tmp_path) == {}
    assert signal_copy_autorise([LENT, AUTRE], tmp_path) == (True, None)
    (tmp_path / CHEMIN_PLAN_LABO).write_text("{illisible", encoding="utf-8")
    assert signal_copy_autorise([LENT, AUTRE], tmp_path) == (True, None)   # illisible : ni blocage ni ouverture


def test_leader_mesure_hft_est_refuse_meme_whiteliste(tmp_path):
    _whitelist(tmp_path, [LENT, ROBOT])
    _plan(tmp_path, [
        {"unit": LENT, "addresses": [LENT], "archetype": "DIRECTIONAL_SLOW"},
        {"unit": ROBOT, "addresses": [ROBOT, CLONE], "archetype": "HFT"},
    ])
    assert signal_copy_autorise([LENT], tmp_path) == (True, None)
    assert signal_copy_autorise([ROBOT.upper().replace("0X", "0x")], tmp_path) == (False, MOTIF_NON_COPIABLE_LABO)
    assert signal_copy_autorise([LENT, ROBOT], tmp_path) == (False, MOTIF_NON_COPIABLE_LABO)


def test_consensus_de_clones_d_un_meme_operateur_n_est_pas_un_consensus(tmp_path):
    _whitelist(tmp_path, [LENT, AUTRE, ROBOT, CLONE])
    _plan(tmp_path, [
        {"unit": ROBOT, "addresses": [ROBOT, CLONE], "archetype": "SWING"},
        {"unit": LENT, "addresses": [LENT], "archetype": "DIRECTIONAL_SLOW"},
    ])
    assert signal_copy_autorise([ROBOT, CLONE], tmp_path) == (False, MOTIF_CONSENSUS_CLONES)
    assert signal_copy_autorise([ROBOT, LENT], tmp_path) == (True, None)        # deux opérateurs distincts
    assert signal_copy_autorise([ROBOT], tmp_path) == (True, None)              # un seul votant : pas un consensus
    assert signal_copy_autorise([LENT, AUTRE], tmp_path) == (True, None)        # AUTRE non mesuré = opérateur propre


def test_les_mesures_du_labo_ne_contournent_jamais_la_whitelist(tmp_path):
    _whitelist(tmp_path, [LENT])
    _plan(tmp_path, [{"unit": AUTRE, "addresses": [AUTRE], "archetype": "DIRECTIONAL_SLOW"}])
    assert signal_copy_autorise([AUTRE], tmp_path) == (False, MOTIF_HORS_LISTE)  # « lent » n'est pas « autorisé »

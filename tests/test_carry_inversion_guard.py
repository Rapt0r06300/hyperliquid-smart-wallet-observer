"""GARDE ANTI-RÉGRESSION — l'inversion du funding N'EST PAS un gate du scanner.

Une PORTE 3bis d'inversion (ajoutée puis RETIRÉE le 16/07) refusait PURR — le carry phare du projet
(98 % d'heures positives) — parce que le helper de test empile les heures négatives À LA FIN de la
série, ce qu'un garde-fou de récence lit comme une inversion. Leçon : le scanner juge **moyenne +
stabilité** (son contrat testé) ; la sélection sensible à l'inversion vit dans `carry_ranking`
(couche de timing), sur des données chronologiques fournies par l'appelant.

Ce test verrouille les DEUX faits pour qu'on ne réintroduise pas la régression.
"""
from __future__ import annotations

from hl_observer.strategies.carry_ranking import classer
from hl_observer.strategies.carry_scanner import scanner

SPOT = {"PURR"}


def _positif_stable_mais_fin_negative() -> list[float]:
    """Moyenne positive (~0,29) et 97 % d'heures positives, mais les dernières heures sont négatives."""
    return [0.31] * 700 + [-0.30] * 20


def test_le_scanner_RETIENT_un_carry_positif_stable_meme_si_la_fin_de_serie_est_negative() -> None:
    p = scanner({"PURR": _positif_stable_mais_fin_negative()}, spot_carryables=SPOT)[0]
    assert p.retenu is True        # AUCUN gate d'inversion dans le scanner (sinon PURR sauterait)


def test_l_inversion_est_geree_dans_le_ranking_pas_dans_le_scanner() -> None:
    # Sur des données chronologiques, carry_ranking écarte un funding qui s'inverse vraiment.
    cl = classer(
        {"INV": [0.2, -0.3, -0.5, -0.4, -0.6, -0.8, -0.83, -0.9]},
        cout_amorti_bps_h=0.5,
    )
    assert cl == []                # écarté par la couche de sélection, pas par le scanner

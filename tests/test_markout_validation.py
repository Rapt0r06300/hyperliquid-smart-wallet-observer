"""Validation du filtre de toxicité (VPIN + markout par côté) déjà branché en porte 6.

Sa seule valeur est de dire QUAND NE PAS TRADER : un flux informé/déséquilibré = on s'abstient.
On vérifie que la porte se déclenche bien sur un flux toxique et se tait sur un flux équilibré,
et qu'un VPIN non mesurable → abstention (deny-by-default, jamais un « pas toxique » inventé).
"""
from __future__ import annotations

from hl_observer.market.flow_toxicity import (
    ACHAT,
    MIN_TRADES,
    SEUIL_VPIN_TOXIQUE,
    VENTE,
    Trade,
    faut_il_s_abstenir,
    ofi,
    vpin,
)


def _flux(cotes: list[str]) -> list[Trade]:
    return [Trade(time_ms=i, prix=100.0, taille=1.0, cote_agresseur=c) for i, c in enumerate(cotes)]


def test_vpin_non_mesurable_donne_abstention() -> None:
    # moins de MIN_TRADES → vpin None → on s'abstient (on ne devine pas « flux sain »).
    v = vpin(_flux([ACHAT, VENTE] * 5))
    assert v is None
    abstenir, _ = faut_il_s_abstenir(v)
    assert abstenir is True


def test_flux_unilateral_est_toxique_et_declenche_l_abstention() -> None:
    v = vpin(_flux([ACHAT] * (MIN_TRADES + 100)))    # 100 % agresseurs acheteurs = informé
    assert v is not None and v >= SEUIL_VPIN_TOXIQUE
    abstenir, _ = faut_il_s_abstenir(v)
    assert abstenir is True


def test_flux_equilibre_n_est_pas_toxique() -> None:
    v = vpin(_flux([ACHAT, VENTE] * (MIN_TRADES)))   # 50/50 alterné = non informé
    assert v is not None and v < SEUIL_VPIN_TOXIQUE
    abstenir, _ = faut_il_s_abstenir(v)
    assert abstenir is False


def test_ofi_ne_fabrique_jamais_un_zero() -> None:
    assert ofi([]) is None                 # vide → None, jamais 0 (0 = « équilibré », un mensonge)
    assert ofi(_flux([ACHAT] * 10)) == 1.0
    assert ofi(_flux([VENTE] * 10)) == -1.0

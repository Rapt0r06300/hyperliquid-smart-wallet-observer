"""#531 / H-126 -- « encaisser le funding avant la publication ».

Le mecanisme est REEL (la doc : le paiement se fait *a la fin de l'intervalle*, non prorate).
La question n'est pas « est-ce possible » mais « est-ce que ca PAIE ».

Ces tests gardent :
  * les seuils viennent de la **source unique de verite des frais**, pas d'un chiffre en dur ;
  * le seuil HONNETE inclut le **bruit de prix** qu'on subit en portant la position
    (*c'est exactement le terme que j'avais oublie dans T1b, et qui l'a tue*) ;
  * `None` plutot qu'un 0 invente quand il n'y a pas de donnee.
"""
from __future__ import annotations

import pytest

from hl_observer.collection.funding_backfill import PointFunding
from hl_observer.funding.snapshot_capture import (
    BRUIT_PRIX_1MIN_BPS,
    COUT_MAKER_ALLER_RETOUR_BPS,
    COUT_TAKER_ALLER_RETOUR_BPS,
    MOTIF_AUCUNE_HEURE_RENTABLE,
    MOTIF_HEURES_TROUVEES,
    evaluer,
    evaluer_coin,
    verdict,
)

T0 = 1_700_000_000_000
H = 3_600_000


def _pts(coin: str, taux_bps: list[float]) -> list[PointFunding]:
    return [PointFunding(coin, T0 + i * H, b / 1e4) for i, b in enumerate(taux_bps)]


def test_les_seuils_viennent_de_la_SOURCE_UNIQUE_de_verite() -> None:
    """9,0 bps taker / 3,0 bps maker -- derives de la grille officielle, pas ecrits a la main."""
    assert COUT_TAKER_ALLER_RETOUR_BPS == pytest.approx(9.0)
    assert COUT_MAKER_ALLER_RETOUR_BPS == pytest.approx(3.0)
    assert COUT_TAKER_ALLER_RETOUR_BPS == pytest.approx(3.0 * COUT_MAKER_ALLER_RETOUR_BPS)


def test_le_funding_MEDIAN_ne_paie_JAMAIS_un_aller_retour() -> None:
    """0,125 bps/h de mediane contre 9,0 bps de couts. **Il faut 72x la mediane.**"""
    c = evaluer_coin("BTC", _pts("BTC", [0.125] * 500))
    assert c is not None
    assert c.n_au_dessus_taker == 0
    assert c.n_au_dessus_maker == 0
    assert COUT_TAKER_ALLER_RETOUR_BPS / 0.125 == pytest.approx(72.0)


def test_une_heure_extreme_passe_le_seuil_des_COUTS() -> None:
    c = evaluer_coin("X", _pts("X", [0.1, 0.1, 12.0, 0.1]))
    assert c is not None
    assert c.n_au_dessus_taker == 1
    assert c.max_bps_h == pytest.approx(12.0)


def test_le_SEUIL_HONNETE_inclut_le_BRUIT_DE_PRIX_le_terme_que_T1b_m_a_appris() -> None:
    """🔴 12 bps de funding passent les 9 bps de couts... mais PAS 9 + 4,5 de bruit de prix.

    *Le terme que j'avais oublie dans T1b -- et qui l'a tue.* On ne l'oublie pas deux fois.
    """
    c = evaluer_coin("X", _pts("X", [12.0]))
    assert c is not None
    assert c.n_au_dessus_taker == 1              # passe les COUTS
    assert c.n_au_dessus_taker_et_bruit == 0     # mais PAS le prix qu'on subit
    assert BRUIT_PRIX_1MIN_BPS > 0.0

    c2 = evaluer_coin("X", _pts("X", [20.0]))
    assert c2 is not None and c2.n_au_dessus_taker_et_bruit == 1


def test_le_signe_du_funding_ne_compte_PAS_on_prend_la_valeur_absolue() -> None:
    """Funding negatif -> on est LONG et on encaisse. Le mecanisme marche dans les deux sens."""
    c = evaluer_coin("X", _pts("X", [-15.0]))
    assert c is not None and c.n_au_dessus_taker == 1


def test_aucune_donnee_rend_None_pas_un_zero_invente() -> None:
    assert evaluer_coin("BTC", []) is None
    assert evaluer_coin("BTC", _pts("ETH", [10.0])) is None      # mauvais coin


def test_le_verdict_dit_la_verite_meme_quand_il_trouve_des_heures() -> None:
    v = verdict(evaluer(_pts("X", [20.0, 0.1, 0.1]) + _pts("Y", [0.1] * 10)))
    assert v["n_heures_total"] == 13
    assert v["n_heures_qui_paient_un_aller_retour"] == 1
    assert v["n_heures_qui_paient_AR_ET_le_bruit_de_prix"] == 1
    assert v["motif"] == MOTIF_HEURES_TROUVEES
    assert "Compter des heures n'est pas gagner de l'argent" in v["avertissement"]
    assert v["real_execution"] is False


def test_le_verdict_quand_RIEN_ne_passe() -> None:
    v = verdict(evaluer(_pts("X", [0.125] * 100)))
    assert v["n_heures_qui_paient_AR_ET_le_bruit_de_prix"] == 0
    assert v["motif"] == MOTIF_AUCUNE_HEURE_RENTABLE


def test_le_classement_met_en_tete_le_coin_qui_a_le_PLUS_d_heures_payantes() -> None:
    cs = evaluer(_pts("A", [20.0, 20.0, 0.1]) + _pts("B", [20.0]))
    assert [c.coin for c in cs] == ["A", "B"]

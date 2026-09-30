"""Le verdict NET de la piste liquidations : le markout BRUT passe par le noyau de coûts.

Le cas qui compte : un markout brut POSITIF peut devenir NÉGATIF une fois les frais payés.
On refuse de se mentir — c'est exactement la discipline « un markout brut n'est pas un edge net ».
"""
from __future__ import annotations

from hl_observer.backtesting.liquidation_net import (
    COUT_MAKER_ALLER_RETOUR_BPS,
    COUT_TAKER_ALLER_RETOUR_BPS,
    edge_net_liquidation,
    meilleur_horizon_net,
)


def test_markout_brut_positif_mais_MANGE_par_les_frais_devient_negatif() -> None:
    # markout brut = 6 bps ; taker aller-retour = 9 bps → net = -3 → REJET.
    r = edge_net_liquidation(6.0)  # taker par défaut
    assert r.net_edge_bps == 6.0 - COUT_TAKER_ALLER_RETOUR_BPS
    assert r.net_edge_bps < 0.0
    assert r.accepted is False


def test_markout_brut_assez_gros_survit_aux_frais() -> None:
    # markout brut = 20 bps ; taker 9 → net = 11 > 0 → net-positif.
    r = edge_net_liquidation(20.0, min_edge_bps=0.0)
    assert r.net_edge_bps == 11.0
    assert r.accepted is True


def test_maker_coute_moins_cher_que_taker() -> None:
    brut = 8.0
    net_taker = edge_net_liquidation(brut, en_maker=False).net_edge_bps
    net_maker = edge_net_liquidation(brut, en_maker=True).net_edge_bps
    # 8 - 9 = -1 (taker, rejeté) ; 8 - 3 = 5 (maker, survit)
    assert net_taker == brut - COUT_TAKER_ALLER_RETOUR_BPS
    assert net_maker == brut - COUT_MAKER_ALLER_RETOUR_BPS
    assert net_maker > net_taker


def test_le_spread_se_soustrait_aussi() -> None:
    sans = edge_net_liquidation(20.0).net_edge_bps
    avec = edge_net_liquidation(20.0, spread_bps=4.0).net_edge_bps
    assert avec == sans - 4.0        # le spread est un coût de plus


def test_meilleur_horizon_choisit_le_meilleur_NET_pas_le_meilleur_brut() -> None:
    # deux horizons ; le noyau de coûts est commun, donc le meilleur brut = le meilleur net ici.
    res = meilleur_horizon_net({1.0: 5.0, 10.0: 25.0, 60.0: 12.0})
    assert res is not None
    h, verdict = res
    assert h == 10.0
    assert verdict.net_edge_bps == 25.0 - COUT_TAKER_ALLER_RETOUR_BPS
    assert verdict.accepted is True


def test_dict_vide_renvoie_None_pas_un_zero_invente() -> None:
    assert meilleur_horizon_net({}) is None

"""LA PROFONDEUR DU CARNET — *le prix AFFICHE n'est pas le prix qu'on OBTIENT.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CES TESTS PROTEGENT
═══════════════════════════════════════════════════════════════════════════════════════════════

Le bot ouvre 3 carrys sur de **petits marches** (PURR, PUMP, HYPE). Leur funding est eleve
**precisement parce que les detenir est dangereux** -- le funding EST le prix de ce risque.

Si le carnet est mince, le slippage mange l'edge. Et il le mange **4 fois** (spot achat, spot
vente, perp vente, perp achat).

🔴 **L'ILLUSION A TUER** : prendre le **meilleur prix** et supposer qu'il tient pour toute la
taille. *C'est exactement ce qui a fabrique le faux edge de +31 bps dans T1 (bid-ask bounce).*

-> **on MARCHE dans le carnet, niveau par niveau.** Et si la profondeur ne suffit pas,
   on renvoie `rempli=False` -- **jamais un prix moyen fantome.**

Aucun ordre reel. Paper-only.
"""
from __future__ import annotations

import pytest

from hl_observer.market.spot_depth import (
    SLIPPAGE_ABSURDE_BPS,
    marcher_dans_le_carnet,
    niveaux,
    verdict_carry,
)


def _book(bids, asks) -> dict:
    return {"levels": [[{"px": str(p), "sz": str(s)} for p, s in bids],
                       [{"px": str(p), "sz": str(s)} for p, s in asks]]}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. LIRE LE CARNET — deny-by-default
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_un_carnet_illisible_donne_une_liste_VIDE_jamais_un_prix_invente() -> None:
    for mauvais in ({}, None, {"levels": []}, {"levels": [[]]}, {"levels": "nope"},
                    {"levels": [[{"px": "abc", "sz": "1"}], []]}):
        assert niveaux(mauvais, 0) == []


def test_un_niveau_illisible_est_ECARTE_pas_devine() -> None:
    b = {"levels": [[{"px": "10", "sz": "5"}, {"px": "oops", "sz": "5"},
                     {"px": "9", "sz": "0"}], []]}
    assert niveaux(b, 0) == [(10.0, 5.0)]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. 🔑 MARCHER DANS LE CARNET — *le meilleur prix ne tient pas pour toute la taille.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_le_slippage_est_ZERO_si_le_premier_niveau_suffit() -> None:
    m = marcher_dans_le_carnet([(100.0, 100.0)], 500.0)
    assert m.rempli and m.prix_moyen == pytest.approx(100.0)
    assert m.slippage_bps == pytest.approx(0.0)


def test_LE_TEST_QUI_COMPTE_on_marche_dans_le_carnet_et_le_prix_monte() -> None:
    """🔑 500 $ a prendre. Le meilleur niveau n'en porte que 100 $. **On paie plus cher.**

    niveaux : 100 $ @ 100,0  ·  100 $ @ 101,0  ·  1000 $ @ 102,0
    -> 100 + 100 + 300 pris    -> prix moyen **strictement > 100**.

    ***Si le slippage ressort a 0, c'est qu'on n'a PAS marche : on a triche.***
    """
    lv = [(100.0, 1.0), (101.0, 0.990099), (102.0, 9.803922)]   # ~100 $, ~100 $, ~1000 $
    m = marcher_dans_le_carnet(lv, 500.0)
    assert m.rempli
    assert m.prix_moyen > 100.0, "REGRESSION : on a pris le meilleur prix pour TOUTE la taille"
    assert m.slippage_bps > 0.0
    assert m.prix_reference == pytest.approx(100.0)


def test_un_carnet_TROP_MINCE_refuse_et_ne_fabrique_PAS_de_prix_moyen() -> None:
    """*Ne pas savoir n'est pas une permission.*"""
    m = marcher_dans_le_carnet([(100.0, 0.5)], 500.0)   # 50 $ dispo pour 500 $ voulus
    assert m.rempli is False
    assert m.prix_moyen == 0.0, "un prix moyen sur une taille non obtenue est un prix FANTOME"


def test_un_carnet_vide_refuse() -> None:
    assert marcher_dans_le_carnet([], 500.0).rempli is False


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. LE VERDICT — l'edge survit-il ? **Les 4 jambes, pas une.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════

_PROFOND = [(100.0, 1000.0)]          # carnet epais -> slippage nul
_MINCE = [(100.0, 0.1)]               # 10 $ dispo


def _m(lv, n=500.0):
    return marcher_dans_le_carnet(lv, n)


def test_une_seule_jambe_MINCE_suffit_a_refuser_tout_le_carry() -> None:
    """🔒 Un carry a **QUATRE** jambes. *Une seule qui ne passe pas, et le carry n'existe pas.*"""
    v = verdict_carry(0.1131, _m(_PROFOND), _m(_PROFOND), _m(_PROFOND), _m(_MINCE))
    assert v.survit is False
    assert "MINCE" in v.verdict


def test_un_carnet_profond_laisse_l_edge_INTACT() -> None:
    v = verdict_carry(0.1131, _m(_PROFOND), _m(_PROFOND), _m(_PROFOND), _m(_PROFOND))
    assert v.survit is True
    assert v.slippage_total_bps == pytest.approx(0.0)
    assert v.apr_apres_slippage == pytest.approx(0.1131)


def test_le_slippage_REDUIT_l_APR_il_ne_l_augmente_jamais() -> None:
    lv = [(100.0, 1.0), (101.0, 1.0), (105.0, 100.0)]
    v = verdict_carry(0.1131, _m(lv), _m(lv), _m(lv), _m(lv))
    assert v.slippage_total_bps > 0
    assert v.apr_apres_slippage < 0.1131, "le slippage est un COUT : il ne peut pas enrichir"


def test_un_slippage_qui_MANGE_TOUT_donne_NO_TRADE() -> None:
    """🔴 Un carry a **4,48 %** d'APR ne survit pas a un carnet qui coute des centaines de bps."""
    lv = [(100.0, 0.01), (140.0, 100.0)]     # le 2e niveau est 40 % plus haut
    v = verdict_carry(0.0448, _m(lv), _m(lv), _m(lv), _m(lv))
    assert v.survit is False
    assert v.apr_apres_slippage <= 0 or v.slippage_total_bps >= SLIPPAGE_ABSURDE_BPS


def test_un_APR_apres_slippage_negatif_n_est_JAMAIS_presente_comme_un_gain() -> None:
    lv = [(100.0, 1.0), (103.0, 100.0)]
    v = verdict_carry(0.001, _m(lv), _m(lv), _m(lv), _m(lv))
    assert not v.survit
    assert "NO_TRADE" in v.verdict

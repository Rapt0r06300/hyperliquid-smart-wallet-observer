"""#571 / #567 / #573 / #574 / #579 -- les metriques qu'on n'avait pas.

🔴 LE TEST QUI COMPTE : `test_notre_strategie_ne_bat_PAS_le_buy_and_hold`.
On a produit des dizaines de rapports de PnL. **Aucun n'a jamais affiche le buy-and-hold.**
Un edge a -7,97 bps est battu par NE RIEN FAIRE -- et ne rien faire n'a ni frais, ni spread,
ni slippage, ni latence, ni liquidation.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.honest_metrics import (
    MIN_TRADES,
    MOTIF_PAS_ASSEZ_DE_TRADES,
    buy_and_hold,
    comparer_au_buy_and_hold,
    double_drawdown,
    esperance,
    pire_periode,
)


# ════════════════════════════════════════════════════════════════════════════════════════════
# #571 — LE BENCHMARK QU'ON N'A JAMAIS AFFICHE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_buy_and_hold_n_a_AUCUN_cout() -> None:
    r, dd = buy_and_hold([100.0, 110.0, 90.0, 120.0])
    assert r == pytest.approx(0.20)          # +20 %, brut de tout
    assert dd == pytest.approx(90.0 / 110.0 * -1 + 1, abs=1e-9)   # -18,18 % depuis le sommet


def test_notre_strategie_est_DOMINEE_PAR_LE_CASH() -> None:
    """🔴🔴 LE VERDICT — et **ce test a demoli ma 1re regle**.

    Marche : +20 %. Strategie a edge negatif : **-5 %**, drawdown 6,9 % (plus PETIT que les
    18,2 % du marche).

    Ma 1re version la declarait « justifiee » : *elle bat le B&H sur le drawdown !*
    **Absurde.** Le CASH rend 0 % avec 0 % de drawdown.
    *Une strategie a rendement negatif est dominee par NE RIEN FAIRE DU TOUT, sur les DEUX
    dimensions a la fois.* Et notre edge mesure est de **-7,97 bps**.
    """
    marche = [100.0, 110.0, 90.0, 120.0]
    strat = [1000.0, 1010.0, 940.0, 950.0]     # rend -5 %, dd 6,9 %
    c = comparer_au_buy_and_hold(strat, marche)
    assert c.bat_le_drawdown, "elle bat bien le B&H sur le drawdown..."
    assert not c.bat_le_rendement
    assert c.domine_par_le_cash, "... mais elle PERD DE L'ARGENT."
    assert not c.justifie_son_existence
    assert "DOMINEE PAR LE CASH" in c.as_dict()["verdict"]
    assert c.as_dict()["rendement_cash"] == 0.0 and c.as_dict()["dd_cash"] == 0.0


def test_une_strategie_qui_SOUFFRE_MOINS_justifie_son_existence() -> None:
    """⚠️ HONNETETE : le B&H n'est PAS sans risque. Perdre moins en baisse a une VALEUR.

    On ne condamne donc pas une strategie sur le seul rendement.
    """
    marche = [100.0, 50.0, 80.0]               # krach : -20 %, drawdown -50 %
    strat = [1000.0, 1005.0, 1010.0]           # +1 %, drawdown 0 % -> elle bat AUSSI le cash
    c = comparer_au_buy_and_hold(strat, marche)
    assert c.bat_le_rendement and c.bat_le_drawdown
    assert not c.domine_par_le_cash, "elle GAGNE de l'argent : le cash ne la domine pas"
    assert c.justifie_son_existence


def test_perdre_moins_que_le_marche_ne_SUFFIT_PAS_si_on_perd_quand_meme() -> None:
    """⚠️ Le contre-exemple honnete : -1,5 % dans un krach a -20 %, c'est **mieux que le marche**…

    …mais le CASH aurait fait **0 %**. La strategie reste dominee. **On le dit.**
    """
    c = comparer_au_buy_and_hold([1000.0, 990.0, 985.0], [100.0, 50.0, 80.0])
    assert c.bat_le_rendement and c.bat_le_drawdown      # elle bat le B&H sur TOUT
    assert c.domine_par_le_cash                          # ... et le cash la bat quand meme
    assert not c.justifie_son_existence


def test_un_marche_sans_prix_ne_fabrique_pas_de_benchmark() -> None:
    assert buy_and_hold([]) == (0.0, 0.0)
    assert buy_and_hold([100.0]) == (0.0, 0.0)
    assert buy_and_hold([0.0, -5.0]) == (0.0, 0.0)     # prix absurdes ECARTES


# ════════════════════════════════════════════════════════════════════════════════════════════
# #567 + #573 — DEUX DRAWDOWNS. Le premier est TOUJOURS plus flatteur.
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_drawdown_sur_trades_clotures_CACHE_la_douleur_vecue() -> None:
    """La courbe des cloture ne bouge qu'aux sorties -> elle ignore la position ouverte qui saigne."""
    par_tick = [1000.0, 950.0, 800.0, 900.0, 1010.0]     # on a VECU -20 %
    aux_cloture = [1000.0, 1000.0, 1000.0, 1000.0, 1010.0]  # ... rien n'apparait avant la sortie
    d = double_drawdown(par_tick, aux_cloture)
    assert d.dd_equity == pytest.approx(0.20)
    assert d.dd_trades_clotures == pytest.approx(0.0)
    assert d.ecart == pytest.approx(0.20), "**20 % de douleur, invisible dans le rapport**"


def test_le_drawdown_clotures_est_TOUJOURS_inferieur_ou_egal() -> None:
    par_tick = [100.0, 80.0, 120.0, 60.0, 130.0]
    aux_cloture = [100.0, 100.0, 120.0, 120.0, 130.0]
    d = double_drawdown(par_tick, aux_cloture)
    assert d.dd_trades_clotures <= d.dd_equity
    assert d.ecart >= 0.0


# ════════════════════════════════════════════════════════════════════════════════════════════
# #574 — L'ESPERANCE. Un winrate n'est PAS une esperance.
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_winrate_de_87_pourcent_peut_etre_une_MACHINE_A_PERDRE() -> None:
    """🔴 C'est **exactement** ce que l'autopsie du -64 $ a trouve : breakeven a 87 %.

    26 gains de +1 $, 4 pertes de -10 $ -> winrate 86,7 %, esperance **negative**.
    """
    pnls = [1.0] * 26 + [-10.0] * 4
    e = esperance(pnls)
    assert e.suffisant
    assert e.winrate == pytest.approx(26 / 30, abs=1e-4)      # 86,7 %
    assert e.esperance < 0.0, "un winrate flatteur ne sauve pas une esperance negative"
    assert e.profit_factor is not None and e.profit_factor < 1.0
    # et le winrate qu'il FAUDRAIT :
    assert e.winrate_de_breakeven == pytest.approx(10.0 / 11.0, abs=1e-4)   # 90,9 %
    assert e.winrate < e.winrate_de_breakeven


def test_moins_de_20_trades_ne_donne_AUCUN_chiffre() -> None:
    """*Un seul essai chanceux ne prouve rien.* (La lecon du +95 bps sur 1 trade.)"""
    e = esperance([5.0] * 19)
    assert not e.suffisant
    assert MOTIF_PAS_ASSEZ_DE_TRADES in e.motif
    assert e.esperance == 0.0 and e.profit_factor is None
    assert MIN_TRADES == 20


def test_une_esperance_positive_est_reconnue() -> None:
    e = esperance([2.0] * 15 + [-1.0] * 15)
    assert e.suffisant and e.esperance == pytest.approx(0.5)
    assert e.profit_factor == pytest.approx(2.0)


def test_aucune_perte_ne_fait_pas_diviser_par_zero() -> None:
    e = esperance([1.0] * 25)
    assert e.profit_factor is None          # pas d'infini fabrique
    assert e.esperanc
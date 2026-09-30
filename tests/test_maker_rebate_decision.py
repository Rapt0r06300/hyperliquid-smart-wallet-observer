"""D17 — rebate maker ciblé : ne poster que si le rebate bat la sélection adverse (sinon = MM mort)."""
from __future__ import annotations

import pytest

from hl_observer.backtesting.maker_rebate_decision import ev_maker_bps, poster_maker


def test_ev_maker():
    # 50% fill × 2 bps rebate − 3 bps adverse = 1 - 3 = -2
    assert ev_maker_bps(0.5, 2.0, 3.0) == pytest.approx(-2.0)


def test_poster_seulement_si_ev_positive():
    assert poster_maker(0.8, 5.0, 1.0) is True         # 4 - 1 = +3 -> poster
    assert poster_maker(0.5, 2.0, 3.0) is False         # -2 -> ne pas poster (selection adverse domine)


def test_selection_adverse_qui_domine_refuse_le_MM():
    # cas typique de notre venue : adverse (8) >> rebate espere (0.4*2=0.8) -> refus
    assert poster_maker(0.4, 2.0, 8.0) is False


def test_prob_fill_bornee():
    assert ev_maker_bps(2.0, 3.0, 0.0) == pytest.approx(3.0)   # prob>1 bornee a 1
    assert ev_maker_bps(-1.0, 3.0, 0.0) == pytest.approx(0.0)  # prob<0 bornee a 0

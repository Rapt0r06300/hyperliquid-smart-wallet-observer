"""Le modèle de file : correction du double-comptage + invariant fill ≤ 100 %."""
from __future__ import annotations

from hl_observer.backtesting.queue_model import (
    avancer,
    cancels_nets,
    fill_borne_par_100,
    rejouer,
)


def test_correction_du_double_comptage() -> None:
    # un niveau baisse de 10, dont 6 par un trade → 4 sont de vraies annulations.
    assert cancels_nets(chg_carnet=-10.0, qty_trade=6.0) == 4.0
    # si toute la baisse vient du trade, 0 annulation nette.
    assert cancels_nets(chg_carnet=-6.0, qty_trade=6.0) == 0.0


def test_on_avance_uniquement_sur_les_trades() -> None:
    # 100 devant nous ; un tick où le carnet baisse de 50 mais SANS trade → on n'avance pas.
    e = avancer(100.0, chg_carnet=-50.0, qty_trade=0.0)
    assert e.qty_devant == 100.0 and e.rempli is False
    # un trade de 30 → on avance de 30.
    e = avancer(100.0, chg_carnet=-30.0, qty_trade=30.0)
    assert e.qty_devant == 70.0 and e.rempli is False


def test_rempli_seulement_quand_les_trades_cumules_depassent() -> None:
    evts = [(-30.0, 30.0), (-30.0, 30.0), (-30.0, 30.0)]  # 90 tradés < 100
    assert rejouer(100.0, evts).rempli is False
    evts2 = evts + [(-20.0, 20.0)]                         # 110 tradés ≥ 100
    assert rejouer(100.0, evts2).rempli is True


def test_invariant_fill_jamais_avant_le_modele_100pct() -> None:
    # le modèle 100 % remplirait dès le 1er trade ; nous, jamais avant. L'invariant tient.
    evts = [(-5.0, 5.0), (-40.0, 10.0), (-100.0, 100.0), (0.0, 50.0)]
    assert fill_borne_par_100(100.0, evts) is True
    assert fill_borne_par_100(0.0, evts) is True   # déjà en tête → rempli, mais jamais "trop tôt"

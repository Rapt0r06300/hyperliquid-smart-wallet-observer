"""Le rejet d'ordre : plus ça bouge, plus le rejet est probable, et un stop non fiable se DIT."""
from __future__ import annotations

from hl_observer.risk.order_rejection import evaluer_sortie, proba_rejet


def test_calme_pas_de_rejet_chaos_rejet_certain() -> None:
    assert proba_rejet(10.0) == 0.0        # marché calme
    assert proba_rejet(250.0) == 1.0       # cascade
    # au milieu : strictement croissant
    assert 0.0 < proba_rejet(60.0) < proba_rejet(120.0) < 1.0


def test_croissance_monotone() -> None:
    vols = [0, 25, 50, 100, 150, 200, 400]
    p = [proba_rejet(v) for v in vols]
    assert all(p[i] <= p[i + 1] for i in range(len(p) - 1))


def test_le_stop_devient_NON_garanti_quand_ca_bouge() -> None:
    # marché calme → sortie garantie
    v_calme = evaluer_sortie(10.0)
    assert v_calme.garantie is True and v_calme.proba_rejet == 0.0
    # cascade → sortie NON garantie (le noyau doit réduire / NO_TRADE)
    v_chaos = evaluer_sortie(250.0)
    assert v_chaos.garantie is False and v_chaos.proba_rejet == 1.0

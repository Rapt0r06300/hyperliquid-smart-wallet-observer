"""H1 — porte de survie unifiée : tout doit passer, deny-by-default."""
from __future__ import annotations

from hl_observer.backtesting.survival_gate import (
    porte_de_survie, survit_oos, survit_regime, survit_liquidite_reduite, survit_couts_stresses,
)


def test_survit_si_tout_passe():
    v = porte_de_survie(oos_ok=True, regime_ok=True, liquidite_reduite_ok=True, couts_realistes_ok=True)
    assert v.survit is True and v.echecs == ()


def test_un_seul_echec_tue():
    v = porte_de_survie(oos_ok=True, regime_ok=False, liquidite_reduite_ok=True, couts_realistes_ok=True)
    assert v.survit is False and "ECHOUE_AUTRE_REGIME" in v.echecs


def test_donnee_manquante_ne_survit_pas():
    v = porte_de_survie(oos_ok=None, regime_ok=None, liquidite_reduite_ok=None, couts_realistes_ok=None)
    assert v.survit is False and len(v.echecs) == 4


def test_helpers():
    assert survit_oos(10.0) is True and survit_oos(-1.0) is False and survit_oos(None) is False
    assert survit_regime({"bull": 5.0, "bear": 1.0}) is True     # pire regime (bear) > 0
    assert survit_regime({"bull": 5.0, "bear": -2.0}) is False   # un regime perd
    assert survit_regime(None) is False
    assert survit_liquidite_reduite(3.0) is True and survit_liquidite_reduite(-1.0) is False
    assert survit_couts_stresses([5.0, 2.0, 0.5]) is True        # positif meme au pire cout
    assert survit_couts_stresses([5.0, -1.0]) is False
    assert survit_couts_stresses([]) is False

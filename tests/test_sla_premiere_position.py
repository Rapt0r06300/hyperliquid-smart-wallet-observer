from hl_observer.signals.sla_premiere_position import (
    SLA_OK_DIAGNOSTIC, SLA_OK_POSITION, SLA_VIOLE, evaluer_sla)


def test_position_ouverte_respecte():
    r = evaluer_sla(positions_ouvertes=1, diagnostic=None)
    assert r["respecte"] and r["sla"] == SLA_OK_POSITION


def test_zero_position_avec_diagnostic_respecte():
    r = evaluer_sla(positions_ouvertes=0, diagnostic={"diagnostic": "AUCUNE_FAMILLE_DATA_READY"})
    assert r["respecte"] and r["sla"] == SLA_OK_DIAGNOSTIC


def test_zero_position_sans_diagnostic_viole():
    assert evaluer_sla(positions_ouvertes=0, diagnostic=None)["sla"] == SLA_VIOLE
    assert evaluer_sla(positions_ouvertes=0, diagnostic="")["respecte"] is False
    assert evaluer_sla(positions_ouvertes=0, diagnostic={})["respecte"] is False

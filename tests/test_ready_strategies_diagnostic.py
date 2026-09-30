from hl_observer.signals.ready_strategies_diagnostic import (
    DIAG_NO_DATA, DIAG_POSITIONS, DIAG_READY_ZERO, diagnostic_ready_strategies)


def test_ready_mais_zero_position():
    etats = {"bbo-collector": True, "userfills-live": True, "allmids-collector": True}
    d = diagnostic_ready_strategies(etats, positions_ouvertes=0)
    assert d["diagnostic"] == DIAG_READY_ZERO
    assert set(d["familles_pretes"]) == {"copy_vault", "lead_lag", "cross_venue_dislocation"}


def test_aucune_famille_data_ready():
    d = diagnostic_ready_strategies({}, positions_ouvertes=0)
    assert d["diagnostic"] == DIAG_NO_DATA and d["familles_pretes"] == []
    assert "bbo-collector" in d["familles_bloquees"]["lead_lag"]


def test_positions_ouvertes_court_circuite():
    d = diagnostic_ready_strategies({"bbo-collector": True}, positions_ouvertes=3)
    assert d["diagnostic"] == DIAG_POSITIONS

from hl_observer.alerts.local_alerts import LocalAlerts
from hl_observer.signals.all_signals_zero_alert import KIND, evaluer_signaux_tous_a_zero


def test_tous_a_zero_declenche_alerte():
    al = LocalAlerts(enabled=True)
    r = evaluer_signaux_tous_a_zero([{"notional_usd": 0.0}, {"notional_usd": 0}], alerts=al, now_ms=1)
    assert r["tous_a_zero"] and r["n"] == 2 and r["n_non_nuls"] == 0
    assert r["alerte"] and r["alerte"]["kind"] == KIND
    assert al.fired() and al.fired()[0]["kind"] == KIND


def test_un_signal_non_nul_pas_d_alerte():
    al = LocalAlerts(enabled=True)
    r = evaluer_signaux_tous_a_zero([{"notional_usd": 0.0}, {"notional_usd": 50.0}], alerts=al)
    assert r["tous_a_zero"] is False and r["n_non_nuls"] == 1 and r["alerte"] is None
    assert al.fired() == []


def test_cycle_vide_n_est_pas_une_alerte():
    al = LocalAlerts(enabled=True)
    r = evaluer_signaux_tous_a_zero([], alerts=al)
    assert r["tous_a_zero"] is False and r["alerte"] is None


def test_flag_correct_meme_alertes_off():
    r = evaluer_signaux_tous_a_zero([{"notional_usd": 0.0}], alerts=None)
    assert r["tous_a_zero"] is True and r["alerte"] is None

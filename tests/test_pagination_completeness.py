from hl_observer.hyperliquid.pagination_completeness import evaluer_completude


def test_fin_naturelle_est_complete():
    for r in ("empty_response", "completed"):
        c = evaluer_completude(r)
        assert c["complet"] is True and c["tronque"] is False and c["peut_continuer"] is False


def test_cap_atteint_est_tronque_et_peut_continuer():
    c = evaluer_completude("max_pages_reached")
    assert c["complet"] is False and c["tronque"] is True and c["peut_continuer"] is True


def test_timestamp_bloque_tronque_sans_continuation_sure():
    c = evaluer_completude("timestamp_not_progressing")
    assert c["tronque"] is True and c["peut_continuer"] is False


def test_raison_inconnue_deny_by_default():
    c = evaluer_completude("bidon")
    assert c["complet"] is False and c["raison"] == "STOPPED_REASON_INCONNU"

from hl_observer.research.experiment_design import (
    classer_par_information_gain,
    decaler_signaux_controle_negatif,
    plan_factoriel,
    shift_signal_times_as_negative_control,
    suite_basse_discrepance,
    successive_halving,
)


def test_plan_factoriel_produit_cartesien():
    p = plan_factoriel({"a": [1, 2], "b": ["x", "y", "z"]})
    assert len(p) == 6
    assert {"a": 1, "b": "x"} in p and {"a": 2, "b": "z"} in p


def test_halton_dans_unit_et_deterministe():
    s1 = suite_basse_discrepance(2, 5)
    assert s1 == suite_basse_discrepance(2, 5)
    assert all(0.0 <= x < 1.0 and 0.0 <= y < 1.0 for x, y in s1)
    assert abs(s1[0][0] - 0.5) < 1e-9


def test_successive_halving_garde_le_meilleur():
    assert successive_halving([1, 5, 3, 9, 2, 8], lambda c, b: c, facteur=2) == [9]


def test_information_gain_ordonne_par_incertitude():
    r = classer_par_information_gain([{"id": "a", "incertitude": 0.1},
                                      {"id": "b", "incertitude": 0.9},
                                      {"id": "c", "incertitude": 0.5}])
    assert [d["id"] for d in r] == ["b", "c", "a"] and r[0]["rang"] == 1


def test_signal_decale_dans_le_futur_est_rejete_et_jamais_proven():
    rows = [
        {"episode_id": "e1", "signal_ts_ms": 100, "outcome_ts_ms": 200, "net_usd": 3.0},
        {"episode_id": "e2", "signal_ts_ms": 110, "outcome_ts_ms": 210, "net_usd": -1.0},
    ]
    result = shift_signal_times_as_negative_control(rows, shift_ms=150)
    assert result["status"] == "REJECTED"
    assert result["reason"] == "signal_futur_non_causal"
    assert result["proven"] is False
    assert result["n_future_shifted"] == 2
    assert result["shifted_rows"][0]["signal_ts_ms"] == 250
    assert rows[0]["signal_ts_ms"] == 100
    assert decaler_signaux_controle_negatif(rows, shift_ms=150) == result


def test_decalage_ne_fabrique_pas_un_controle_si_aucun_signal_ne_devient_futur():
    result = shift_signal_times_as_negative_control(
        [{"episode_id": "e1", "signal_ts_ms": 100, "outcome_ts_ms": 1000}],
        shift_ms=10,
    )
    assert result["status"] == "UNMEASURABLE"
    assert result["proven"] is False

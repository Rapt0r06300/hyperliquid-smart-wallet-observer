from hl_observer.ops.pnl_experiment_queue import file_experiences_priorisee


def test_file_priorisee_par_gain_attendu():
    exps = [
        {"nom": "elargir_univers", "valeur": 50.0, "proba": 0.3, "cout": 5.0},   # 10
        {"nom": "reduire_fees", "valeur": 40.0, "proba": 0.8, "cout": 2.0},      # 30
    ]
    f = file_experiences_priorisee(exps)
    assert f[0]["nom"] == "reduire_fees" and f[0]["rang"] == 1
    assert f[1]["nom"] == "elargir_univers" and f[1]["rang"] == 2

from hl_observer.backtesting.fast_exact_comparison import comparer_fast_exact


def test_concordance():
    r = comparer_fast_exact({"a": True, "b": False}, {"a": True, "b": False})
    assert r["concordent"] is True and r["n_communs"] == 2


def test_faux_positif_du_fast():
    r = comparer_fast_exact({"a": True}, {"a": False})
    assert r["concordent"] is False and r["faux_positifs"] == ["a"]


def test_faux_negatif_du_fast():
    r = comparer_fast_exact({"a": False}, {"a": True})
    assert r["faux_negatifs"] == ["a"]


def test_une_cle_absente_refuse_la_concordance():
    r = comparer_fast_exact({"a": True}, {"a": True, "b": False})
    assert r["concordent"] is False
    assert r["couverture_complete"] is False
    assert r["missing_in_fast"] == ["b"]
    assert r["status"] == "MISMATCH"


def test_decision_non_booleenne_refusee():
    try:
        comparer_fast_exact({"a": 1}, {"a": True})
    except ValueError as exc:
        assert "bool" in str(exc)
    else:
        raise AssertionError("une décision non booléenne ne doit pas être acceptée")

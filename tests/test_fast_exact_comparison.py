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

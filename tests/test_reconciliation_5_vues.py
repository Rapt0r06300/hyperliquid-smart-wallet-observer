from hl_observer.simulation.reconciliation_5_vues import VUES, reconcilier_5_vues


def test_les_5_vues_concordent():
    r = reconcilier_5_vues({v: 1000.0 for v in VUES})
    assert r["concordent"] is True and r["desaccords"] == [] and r["manquantes"] == []


def test_une_vue_diverge():
    vals = {v: 1000.0 for v in VUES}
    vals["ui"] = 1005.0
    r = reconcilier_5_vues(vals)
    assert r["concordent"] is False
    assert any(d["vue"] == "ui" for d in r["desaccords"])


def test_une_vue_manquante_non_concorde():
    vals = {v: 1000.0 for v in VUES}
    vals["api"] = None
    r = reconcilier_5_vues(vals)
    assert r["concordent"] is False and "api" in r["manquantes"]


def test_tolerance_absorbe_le_bruit_flottant():
    vals = {v: 1000.0 for v in VUES}
    vals["store"] = 1000.0 + 1e-12
    assert reconcilier_5_vues(vals)["concordent"] is True

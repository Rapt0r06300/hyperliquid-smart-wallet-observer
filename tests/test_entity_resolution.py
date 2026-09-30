import pytest

from hl_observer.research.entity_resolution import resoudre_entites, provenance_label


def test_resoudre_entites_union_find():
    r = resoudre_entites([("w1", "w2"), ("w2", "w3"), ("w4", "w5")])
    assert r["n_entites"] == 2
    assert ["w1", "w2", "w3"] in r["entites"] and ["w4", "w5"] in r["entites"]


def test_provenance_label_obligatoire():
    lab = provenance_label("smart_money", source="nansen", asof=1000.0)
    assert lab["tracable"] is True and lab["source"] == "nansen"
    with pytest.raises(ValueError):
        provenance_label("orphelin", source="", asof=0.0)

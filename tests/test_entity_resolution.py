import pytest

from hl_observer.research.entity_resolution import (
    provenance_label,
    resoudre_entites,
)


def test_resoudre_entites_union_find():
    r = resoudre_entites([("w1", "w2"), ("w2", "w3"), ("w4", "w5")])
    assert r["n_entites"] == 2
    assert ["w1", "w2", "w3"] in r["entites"] and ["w4", "w5"] in r["entites"]


def test_provenance_label_obligatoire():
    lab = provenance_label("smart_money", source="nansen", asof=1000.0)
    assert lab["tracable"] is True and lab["source"] == "nansen"
    with pytest.raises(ValueError):
        provenance_label("orphelin", source="", asof=0.0)


def test_legacy_links_remain_available_but_are_not_measurable():
    result = resoudre_entites([("w1", "w2")])
    assert result["entites"] == [["w1", "w2"]]
    assert result["measurement_status"] == "UNMEASURABLE"
    assert result["provenance_complete"] is False
    assert result["rejected_links"][0]["reason"] == "MISSING_POINT_IN_TIME_PROVENANCE"


def test_point_in_time_links_reject_future_and_missing_provenance():
    result = resoudre_entites([
        {"wallet_a": "w1", "wallet_b": "w2", "source": "safe-observation",
         "asof": 100.0, "evidence_id": "obs-1"},
        {"wallet_a": "w2", "wallet_b": "w3", "source": "safe-observation",
         "asof": 101.0, "evidence_id": "obs-future"},
    ], cutoff_asof=100.0)
    assert result["entites"] == [["w1", "w2"]]
    assert result["accepted_links"] == 1
    assert result["measurement_status"] == "UNMEASURABLE"
    assert result["rejected_links"][0]["reason"] == "LINK_AFTER_CUTOFF"

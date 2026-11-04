from hl_observer.simulation.exploratory_vs_validated_pnl import (
    TIER_EXPLORATOIRE, TIER_FORWARD, TIER_REPLAY, TIER_SHADOW, TIER_TRAIN,
    TIER_VALIDE, label_pnl_stage, pnl_valide_seulement, tier_pnl)


def test_tier():
    assert tier_pnl("strict") == TIER_VALIDE
    assert tier_pnl("ALPHA") == TIER_EXPLORATOIRE and tier_pnl("raw_probe") == TIER_EXPLORATOIRE


def test_pas_de_melange():
    r = pnl_valide_seulement({"strict": 12.0, "alpha": 5.0, "raw_probe": -2.0})
    assert r["pnl_valide"] == 12.0                 # seul le strict
    assert r["pnl_exploratoire_separe"] == 3.0     # alpha + probe, SEPARE
    assert r["melange_interdit"] is True


def test_stages_pnl_restent_paper_et_train_ne_devient_jamais_forward():
    assert label_pnl_stage("train")["tier"] == TIER_TRAIN
    assert label_pnl_stage("train")["forward_certified"] is False
    assert label_pnl_stage("shadow")["tier"] == TIER_SHADOW
    assert label_pnl_stage("replay")["tier"] == TIER_REPLAY
    not_frozen = label_pnl_stage("forward", post_freeze=False, economic_certified=True)
    assert not_frozen["tier"] == TIER_FORWARD
    assert not_frozen["status"] == "UNMEASURABLE"
    verified = label_pnl_stage("forward", post_freeze=True, economic_certified=True)
    assert verified["forward_certified"] is True
    assert verified["is_paper"] is True

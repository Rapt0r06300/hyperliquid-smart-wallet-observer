from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.backtesting import economic_vnext_pack as module


def _forbid_disabled_family_work(monkeypatch) -> None:
    names = (
        "select_aligned_bbo_sources",
        "explore_lead_lag_multiasset_train",
        "explore_lead_lag_bbo_repricing_train",
        "load_preferred_certified_atomic_series",
        "explore_cross_venue_v4_train",
        "explore_cross_venue_v5_train",
        "load_certified_atomic_union_series",
        "explore_cross_venue_v6_train",
        "scan_native_cross_venue_prefilter",
    )
    for name in names:
        monkeypatch.setattr(
            module,
            name,
            lambda *_args, **_kwargs: pytest.fail("disabled-family research executed"),
            raising=False,
        )


def test_vnext_pack_nexecute_que_copy_vault_et_ne_certifie_rien(
    tmp_path: Path, monkeypatch
) -> None:
    _forbid_disabled_family_work(monkeypatch)
    alignment_calls: list[object] = []

    def select_sources(_root, *, candidates):
        alignment_calls.append(candidates)
        return [], {"selected_sources": 0}

    monkeypatch.setattr(
        module,
        "select_aligned_bbo_sources",
        lambda *_args, **_kwargs: pytest.fail("Lead-Lag source discovery must remain disabled"),
    )
    monkeypatch.setattr(
        module,
        "explore_lead_lag_multiasset_train",
        lambda *_args, **_kwargs: pytest.fail("Lead-Lag vNext selector must remain disabled"),
    )
    monkeypatch.setattr(
        module,
        "explore_lead_lag_bbo_repricing_train",
        lambda *_args, **_kwargs: pytest.fail("Lead-Lag BBO selector must remain disabled"),
    )
    monkeypatch.setattr(
        module,
        "load_preferred_certified_atomic_series",
        lambda *_args, **_kwargs: pytest.fail("Cross-Venue source load must remain disabled"),
    )
    monkeypatch.setattr(
        module,
        "explore_cross_venue_v4_train",
        lambda *_args, **_kwargs: pytest.fail("Cross-Venue vNext selector must remain disabled"),
    )
    monkeypatch.setattr(
        module,
        "explore_cross_venue_v5_train",
        lambda *_args, **_kwargs: pytest.fail("Cross-Venue persistence selector must remain disabled"),
    )
    monkeypatch.setattr(
        module,
        "_load_copy_raw",
        lambda _root: {
            "next_hypothesis_v4": {
                "status": "NO_ROBUST_TRAIN_CANDIDATE",
                "selection_eligible": False,
                "physical_freeze_allowed": False,
                "heldout_evaluated": False,
            },
            "next_hypothesis_v5": {
                "status": "NO_ROBUST_TRAIN_CANDIDATE",
                "selection_eligible": False,
                "physical_freeze_allowed": False,
                "heldout_evaluated": False,
            },
            "next_hypothesis_v6": {
                "status": "NO_ROBUST_TRAIN_CANDIDATE",
                "selection_eligible": False,
                "physical_freeze_allowed": False,
                "heldout_evaluated": False,
            },
            "next_hypothesis_v7": {
                "status": "NO_ROBUST_TRAIN_CANDIDATE",
                "selection_eligible": False,
                "physical_freeze_allowed": False,
                "heldout_evaluated": False,
            },
            "next_hypothesis_v8": {
                "status": "NO_ROBUST_TRAIN_CANDIDATE",
                "selection_eligible": False,
                "physical_freeze_allowed": False,
                "heldout_evaluated": False,
            },
            "next_hypothesis_v9": {
                "status": "NO_ROBUST_TRAIN_CANDIDATE",
                "selection_eligible": False,
                "physical_freeze_allowed": False,
                "heldout_evaluated": False,
            },
        },
    )
    monkeypatch.setattr(
        module,
        "explore_copy_vault_vnext_train",
        lambda _raw: {
            "status": "NO_ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "freeze_candidate_sha256": None,
        },
    )

    result = module.run_economic_vnext_pack(tmp_path, lead_sources=[])

    assert set(result["families"]) == {"lead_lag", "cross_venue", "copy_vault"}
    assert result["canonical_campaigns_mutated"] is False
    assert result["heldout_evaluated"] is False
    assert result["real_execution"] is False
    assert result["certification_status"] == "TRAIN_ONLY_NOT_CERTIFIED"
    assert result["freeze_hash"] is None
    assert result["post_freeze_oos_consumed"] is False
    assert (
        result["research_variants"]["copy_vault_continuation_v4"]["heldout_evaluated"]
        is False
    )
    assert "copy_vault_continuation_v4" in result["reports"]
    assert (
        result["research_variants"]["copy_vault_lifecycle_v5"]["heldout_evaluated"]
        is False
    )
    assert "copy_vault_lifecycle_v5" in result["reports"]
    assert (
        result["research_variants"]["copy_vault_balanced_v6"]["heldout_evaluated"]
        is False
    )
    assert "copy_vault_balanced_v6" in result["reports"]
    assert (
        result["research_variants"]["copy_vault_exit_flow_v7"]["heldout_evaluated"]
        is False
    )
    assert "copy_vault_exit_flow_v7" in result["reports"]
    assert (
        result["research_variants"]["copy_vault_entry_efficiency_v8"][
            "heldout_evaluated"
        ]
        is False
    )
    assert "copy_vault_entry_efficiency_v8" in result["reports"]
    assert (
        result["research_variants"]["copy_vault_online_leader_quality_v9"][
            "heldout_evaluated"
        ]
        is False
    )
    assert "copy_vault_online_leader_quality_v9" in result["reports"]
    assert result["research_variants"]["cross_venue_persistence_v5"]["status"] == "DISABLED_BY_SCOPE"
    assert "cross_venue_persistence_v5" not in result["reports"]
    assert (
        result["research_variants"]["cross_venue_coverage_union_v6"][
            "heldout_evaluated"
        ]
        is False
    )
    assert "cross_venue_coverage_union_v6" not in result["reports"]
    assert (
        result["research_variants"]["lead_lag_bbo_repricing"]["heldout_evaluated"]
        is False
    )
    assert "lead_lag_bbo_repricing" not in result["reports"]
    assert alignment_calls == []
    assert result["lead_source_alignment"]["status"] == "DISABLED_BY_SCOPE"
    assert (
        result["lead_source_alignment"]["source_request_mode"]
        == "DISABLED_BY_SCOPE"
    )
    assert result["active_scope"] == ["copy_vault"]
    assert result["families"]["lead_lag"]["status"] == "DISABLED_BY_SCOPE"
    assert result["families"]["cross_venue"]["status"] == "DISABLED_BY_SCOPE"
    assert "lead_lag" not in result["reports"]
    assert "cross_venue" not in result["reports"]
    assert (tmp_path / result["summary_path"]).is_file()


def test_vnext_pack_ignore_les_sources_lead_lag_hors_scope(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text("", encoding="utf-8")
    alignment_calls: list[object] = []
    _forbid_disabled_family_work(monkeypatch)

    monkeypatch.setattr(
        module,
        "select_aligned_bbo_sources",
        lambda *_args, **_kwargs: pytest.fail("disabled Lead-Lag sources were accessed"),
    )
    monkeypatch.setattr(
        module,
        "explore_lead_lag_multiasset_train",
        lambda _root, _sources: {
            "status": "NO_ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "freeze_candidate_sha256": None,
        },
    )
    monkeypatch.setattr(
        module,
        "explore_lead_lag_bbo_repricing_train",
        lambda _root, *, sources: {
            "status": "NO_ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "freeze_candidate_sha256": None,
            "heldout_evaluated": False,
        },
    )
    monkeypatch.setattr(
        module,
        "load_preferred_certified_atomic_series",
        lambda _root: ({}, {}, {"source_mode": "CERTIFIED_ATOMIC_FOUR_SIDE_BOOK_V2"}),
    )
    monkeypatch.setattr(
        module,
        "explore_cross_venue_v4_train",
        lambda *_args, **_kwargs: {
            "status": "NO_ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "freeze_candidate_sha256": None,
        },
    )
    monkeypatch.setattr(
        module,
        "explore_cross_venue_v5_train",
        lambda *_args, **_kwargs: {
            "status": "NO_ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "freeze_candidate_sha256": None,
            "heldout_evaluated": False,
        },
    )
    monkeypatch.setattr(module, "_load_copy_raw", lambda _root: None)

    result = module.run_economic_vnext_pack(tmp_path, lead_sources=[source])

    assert alignment_calls == []
    assert result["lead_source_alignment"]["status"] == "DISABLED_BY_SCOPE"
    assert (
        result["lead_source_alignment"]["source_request_mode"]
        == "DISABLED_BY_SCOPE"
    )

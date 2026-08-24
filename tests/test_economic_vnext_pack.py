from __future__ import annotations

from pathlib import Path

from hl_observer.backtesting import economic_vnext_pack as module


def test_vnext_pack_garde_les_trois_familles_separees_et_ne_certifie_rien(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        module,
        "select_aligned_bbo_sources",
        lambda _root, candidates: ([], {"selected_sources": 0}),
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
        "load_preferred_certified_atomic_series",
        lambda _root: ({}, {}, {"source_mode": "CERTIFIED_ATOMIC_FOUR_SIDE_BOOK_V2"}),
    )
    monkeypatch.setattr(
        module,
        "explore_cross_venue_v3_train",
        lambda *_args, **_kwargs: {
            "status": "NO_ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "freeze_candidate_sha256": None,
        },
    )
    monkeypatch.setattr(module, "_load_copy_raw", lambda _root: {})
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
    assert (tmp_path / result["summary_path"]).is_file()

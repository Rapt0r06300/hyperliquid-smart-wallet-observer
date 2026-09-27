"""Unit tests for Phase Control and Split Brain Guards."""
from __future__ import annotations

import pytest
from pathlib import Path
from hl_observer.control_plane.phase_control import (
    AlinaPhaseState,
    read_phase_state,
    write_phase_state,
    transition_phase,
)
from hl_observer.control_plane.resumable_campaign import CampaignManifest
from hl_observer.control_plane.split_brain_guard import (
    verify_phase_epoch_guard,
    verify_single_owner_lease,
)


def test_phase_state_serialization(tmp_path):
    p = tmp_path / "alina-phase.json"
    state = AlinaPhaseState(phase="COLLECT", epoch=5)
    write_phase_state(state, p)

    loaded = read_phase_state(p)
    assert loaded.phase == "COLLECT"
    assert loaded.epoch == 5


def test_phase_transitions(tmp_path):
    p = tmp_path / "alina-phase.json"
    s1 = transition_phase("COLLECT", p)
    assert s1.phase == "COLLECT"
    assert s1.epoch == 2
    assert s1.collection_started_at_utc is not None

    s2 = transition_phase("ANALYZE", p)
    assert s2.phase == "ANALYZE"
    assert s2.epoch == 3
    assert s2.source_collection_epoch == 2
    assert s2.analysis_stage == "DRAIN"

    s3 = transition_phase("IDLE", p)
    assert s3.phase == "IDLE"
    assert s3.epoch == 4


def test_split_brain_guards(tmp_path):
    p = tmp_path / "alina-phase.json"
    s_collect = transition_phase("COLLECT", p)

    m_collect = CampaignManifest(
        campaign_id="c1",
        kind="market_collection",
        code_repo="repo",
        code_sha="sha1",
        dataset_repo="repo",
        dataset_generation="v2",
        config_sha256="cfg",
        work_plan_sha256="wp",
        expires_at="2026-12-31T00:00:00Z",
        phase_epoch=2,
    )

    assert verify_phase_epoch_guard(m_collect, s_collect) is True

    m_collect_old_epoch = CampaignManifest(
        campaign_id="c2",
        kind="market_collection",
        code_repo="repo",
        code_sha="sha1",
        dataset_repo="repo",
        dataset_generation="v2",
        config_sha256="cfg",
        work_plan_sha256="wp",
        expires_at="2026-12-31T00:00:00Z",
        phase_epoch=1,
    )

    assert verify_phase_epoch_guard(m_collect_old_epoch, s_collect) is False

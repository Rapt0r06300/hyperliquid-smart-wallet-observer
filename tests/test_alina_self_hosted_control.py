from __future__ import annotations

import pytest

from hl_observer.ops.self_hosted_control import (
    CONTROL_SCHEMA,
    MAX_CYCLE_SECONDS,
    build_control_bundle,
    build_worker_request,
    normalize_control,
)


SHA = "a" * 40


def _control(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "schema": CONTROL_SCHEMA,
        "job_id": "replay-canonique-001",
        "suite": "economic-full",
        "mode": "economic",
        "download": True,
        "max_download_gib": 20.0,
        "stage_timeout_seconds": 3600,
        "cross_budget_s": 20.0,
        "lead_history_sources": 8,
        "max_cycle_seconds": MAX_CYCLE_SECONDS,
        "force": False,
    }
    raw.update(overrides)
    return raw


def test_construit_une_requete_worker_verrouillee_sur_main_et_paper() -> None:
    request = build_worker_request(_control(), project_sha=SHA)
    assert request["project_ref"] == "main"
    assert request["project_sha"] == SHA
    assert request["paper_only"] is True
    assert request["real_execution"] is False
    assert request["start_live_collection"] is False
    assert request["dataset_repository"] == "Rapt0r06300/hypersmart-datasets"


def test_un_json_de_commande_ne_peut_pas_activer_le_trading_ni_la_collecte_live() -> None:
    request = build_worker_request(
        _control(real_execution=True, paper_only=False, start_live_collection=True),
        project_sha=SHA,
    )
    assert request["paper_only"] is True
    assert request["real_execution"] is False
    assert request["start_live_collection"] is False


def test_refuse_suite_inconnue_et_sha_court() -> None:
    with pytest.raises(ValueError):
        build_worker_request(_control(suite="suite-inventee"), project_sha=SHA)
    with pytest.raises(ValueError):
        build_worker_request(_control(), project_sha="abc")


def test_refuse_cycle_superieur_a_dix_huit_heures() -> None:
    with pytest.raises(ValueError):
        normalize_control(_control(max_cycle_seconds=MAX_CYCLE_SECONDS + 1))


def test_bundle_separe_controle_worker_et_garde() -> None:
    bundle = build_control_bundle(_control(force=True), project_sha=SHA)
    assert bundle["guard"]["force"] is True
    assert bundle["guard"]["max_cycle_seconds"] == MAX_CYCLE_SECONDS
    assert bundle["security"] == {
        "paper_only": True,
        "real_execution": False,
        "live_collection": False,
        "project_ref": "main",
        "project_sha": SHA,
    }


def test_booléens_de_commande_sont_stricts() -> None:
    with pytest.raises(ValueError):
        normalize_control(_control(download="true"))
    with pytest.raises(ValueError):
        normalize_control(_control(force=1))

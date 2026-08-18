from __future__ import annotations

import pytest

from hl_observer.ops import autonomous_research_job as canonical_job
from hl_observer.ops.family_economic_job import FAMILY_ECONOMIC_SUITES, validate_family_request


def _request(suite: str = "copy-vault-full") -> dict[str, object]:
    return {
        "schema": canonical_job.SCHEMA,
        "job_id": "family-economic-test",
        "suite": suite,
        "mode": "economic",
        "project_ref": "main",
        "project_sha": "a" * 40,
        "release_id": canonical_job.CANONICAL_RELEASE_ID,
        "dataset_repository": canonical_job.CANONICAL_DATASET_REPOSITORY,
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "download": True,
        "max_download_gib": 20.0,
        "stage_timeout_seconds": 3600,
        "cross_budget_s": 20.0,
        "lead_history_sources": 8,
    }


@pytest.mark.parametrize("suite", sorted(FAMILY_ECONOMIC_SUITES))
def test_family_validator_est_pur_et_conserve_la_suite(suite: str) -> None:
    before = set(canonical_job.ECONOMIC_SUITES)
    first = validate_family_request(_request(suite))
    second = validate_family_request(_request(suite))
    assert first == second
    assert first["suite"] == suite
    assert first["mode"] == "economic"
    assert set(canonical_job.ECONOMIC_SUITES) == before


def test_family_validator_refuse_les_suites_non_actives_sans_mutation_globale() -> None:
    before = set(canonical_job.ECONOMIC_SUITES)
    with pytest.raises(ValueError, match="active-family"):
        validate_family_request(_request("sqlite-all-safe"))
    assert set(canonical_job.ECONOMIC_SUITES) == before


def test_family_validator_conserve_tous_les_gardes_canonique() -> None:
    bad = _request()
    bad["real_execution"] = True
    with pytest.raises(ValueError, match="real_execution=false"):
        validate_family_request(bad)


def _workspace(tmp_path, *, status: str = "ATTEINT", eligible: float | None = 4.2, full: bool = True):
    import json
    from pathlib import Path

    workspace = Path(tmp_path) / "workspace"
    campaign_dir = workspace / "runtime" / "reports" / "economic_campaigns"
    coverage_dir = workspace / "runtime" / "reports" / "datasets"
    campaign_dir.mkdir(parents=True)
    coverage_dir.mkdir(parents=True)
    campaign = {
        "family": "copy_vault",
        "objective_status": status,
        "eligible_net_pnl_usd": eligible,
        "paper_read_only": True,
        "real_execution": False,
        "dataset_provenance": {"dataset_fingerprint": "b" * 64},
        "parameter_freeze": {"parameters_sha256": "c" * 64},
    }
    (campaign_dir / "copy_vault.json").write_text(json.dumps(campaign), encoding="utf-8")
    coverage = {
        "families": {
            "copy_vault": {
                "status": "FULL" if full else "PARTIAL",
                "discovered_files": 2,
            }
        }
    }
    (coverage_dir / "SOURCE_CONSUMPTION_COVERAGE.json").write_text(json.dumps(coverage), encoding="utf-8")
    return workspace


def test_economic_memory_est_branchee_sur_une_preuve_atteinte_full(tmp_path) -> None:
    from hl_observer.datasets.economic_memory import load_memory
    from hl_observer.ops.family_economic_job import record_family_economic_memory

    lab = tmp_path / "lab"
    workspace = _workspace(tmp_path)
    record = record_family_economic_memory(
        lab_root=lab, workspace=workspace, suite="copy-vault-full", project_sha="a" * 40
    )
    assert record is not None and record["family"] == "copy_vault"
    assert record["net_pnl_usd"] == 4.2
    memory = load_memory(lab)
    assert memory["proof_count"] == 1


def test_preuve_sous_cible_ne_rentre_pas_dans_la_memoire_certifiee(tmp_path) -> None:
    from hl_observer.datasets.economic_memory import load_memory
    from hl_observer.ops.family_economic_job import record_family_economic_memory

    lab = tmp_path / "lab"
    workspace = _workspace(tmp_path, status="NON_ATTEINT", eligible=None)
    assert record_family_economic_memory(
        lab_root=lab, workspace=workspace, suite="copy-vault-full", project_sha="a" * 40
    ) is None
    assert load_memory(lab)["proofs"] == {}


def test_claim_atteint_sans_couverture_full_est_refuse(tmp_path) -> None:
    from hl_observer.ops.family_economic_job import record_family_economic_memory

    workspace = _workspace(tmp_path, full=False)
    with pytest.raises(RuntimeError, match="not FULL"):
        record_family_economic_memory(
            lab_root=tmp_path / "lab", workspace=workspace,
            suite="copy-vault-full", project_sha="a" * 40,
        )

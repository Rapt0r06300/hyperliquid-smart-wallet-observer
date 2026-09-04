from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.economics.assumptions import EconomicRunMode
from hl_observer.economics.families import build_copy_vault_contract
from hl_observer.ops import autonomous_research_job as canonical_job
from hl_observer.ops.family_economic_job import FAMILY_ECONOMIC_SUITES, validate_family_request
from hl_observer.simulation.economic_objective import evaluate_objective


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


def _segment(*, net: float, hash_char: str, post_freeze: bool = False, no_lookahead: bool = False) -> dict:
    return {
        "sample_count": 1,
        "gross_pnl_usd": net + 0.4,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "net_pnl_usd": net,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 1,
        "trade_ids_sha256": hash_char * 64,
        "post_freeze": post_freeze,
        "no_lookahead": no_lookahead,
    }


def _valid_copy_campaign() -> dict:
    economic_contract = build_copy_vault_contract(
        mode=EconomicRunMode.CERTIFIABLE,
        notional_usd=150.0,
        copy_delay_ms=60_000.0,
        max_reference_lag_ms=30_000.0,
        max_target_lag_ms=30_000.0,
    ).receipt()
    assert economic_contract["certification"]["ready"] is True
    campaign = {
        "family": "copy_vault",
        "starting_capital_usd": 1000.0,
        "paper_read_only": True,
        "real_execution": False,
        "economic_contract": economic_contract,
        "assumption_snapshot_hash": economic_contract["assumption_snapshot_hash"],
        "parameters_frozen": True,
        "opened_positions": 2,
        "closed_positions": 2,
        "gross_pnl_usd": 5.0,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "net_pnl_usd": 4.6,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 2,
        "trade_ids_sha256": "a" * 64,
        "oos": _segment(net=2.1, hash_char="b", no_lookahead=True),
        "forward": _segment(net=2.1, hash_char="c", post_freeze=True),
        "placebos": {"beaten": True},
        "vault_generalization": {"sample_count": 20, "net_bps": 1.0},
        "dataset_provenance": {"dataset_fingerprint": "b" * 64},
        "parameter_freeze": {
            "parameters_sha256": "c" * 64,
            "campaign_id": "copy-vault-fixture-v1",
            "frozen_at_ms": 1_786_552_000_000,
            "selected_before_final_evaluation": True,
            "path": "runtime/reports/economic_campaigns/freezes/copy-vault-fixture-v1.json",
        },
    }
    campaign.update(evaluate_objective(campaign))
    assert campaign["objective_status"] == "ATTEINT"
    assert campaign["eligible_net_pnl_usd"] == pytest.approx(4.2)
    return campaign


def _workspace(tmp_path, *, mode: str = "valid", full: bool = True) -> Path:
    workspace = Path(tmp_path) / "workspace"
    campaign_dir = workspace / "runtime" / "reports" / "economic_campaigns"
    coverage_dir = workspace / "runtime" / "reports" / "datasets"
    campaign_dir.mkdir(parents=True)
    coverage_dir.mkdir(parents=True)

    campaign = _valid_copy_campaign()
    if mode == "non_attained":
        campaign["forward"]["net_pnl_usd"] = -10.0
        campaign.update(evaluate_objective(campaign))
        assert campaign["objective_status"] == "NON_ATTEINT"
    elif mode == "fake_atteint":
        campaign["forward"]["post_freeze"] = False
        campaign["objective_status"] = "ATTEINT"
    elif mode == "fake_eligible":
        campaign["eligible_net_pnl_usd"] = 999.0
    elif mode != "valid":
        raise AssertionError(f"unknown fixture mode: {mode}")

    (campaign_dir / "copy_vault.json").write_text(json.dumps(campaign), encoding="utf-8")
    coverage = {
        "families": {
            "copy_vault": {
                "status": "FULL" if full else "PARTIAL",
                "discovered_files": 2,
            }
        }
    }
    (coverage_dir / "SOURCE_CONSUMPTION_COVERAGE.json").write_text(
        json.dumps(coverage), encoding="utf-8"
    )
    return workspace


def test_economic_memory_est_branchee_sur_une_preuve_recertifiee_full(tmp_path) -> None:
    from hl_observer.datasets.economic_memory import load_memory
    from hl_observer.ops.family_economic_job import record_family_economic_memory

    lab = tmp_path / "lab"
    workspace = _workspace(tmp_path)
    record = record_family_economic_memory(
        lab_root=lab, workspace=workspace, suite="copy-vault-full", project_sha="a" * 40
    )
    assert record is not None and record["family"] == "copy_vault"
    assert record["net_pnl_usd"] == pytest.approx(4.2)
    memory = load_memory(lab)
    assert memory["proof_count"] == 1


def test_preuve_reellement_sous_cible_ne_rentre_pas_dans_la_memoire_certifiee(tmp_path) -> None:
    from hl_observer.datasets.economic_memory import load_memory
    from hl_observer.ops.family_economic_job import record_family_economic_memory

    lab = tmp_path / "lab"
    workspace = _workspace(tmp_path, mode="non_attained")
    assert record_family_economic_memory(
        lab_root=lab, workspace=workspace, suite="copy-vault-full", project_sha="a" * 40
    ) is None
    assert load_memory(lab)["proofs"] == {}


def test_faux_atteint_est_refuse_par_recalcul_canonique(tmp_path) -> None:
    from hl_observer.ops.family_economic_job import record_family_economic_memory

    workspace = _workspace(tmp_path, mode="fake_atteint")
    with pytest.raises(RuntimeError, match="failed canonical recertification"):
        record_family_economic_memory(
            lab_root=tmp_path / "lab", workspace=workspace,
            suite="copy-vault-full", project_sha="a" * 40,
        )


def test_faux_net_eligible_est_refuse_par_recalcul_canonique(tmp_path) -> None:
    from hl_observer.ops.family_economic_job import record_family_economic_memory

    workspace = _workspace(tmp_path, mode="fake_eligible")
    with pytest.raises(RuntimeError, match="failed canonical recertification"):
        record_family_economic_memory(
            lab_root=tmp_path / "lab", workspace=workspace,
            suite="copy-vault-full", project_sha="a" * 40,
        )


def test_claim_atteint_sans_couverture_full_est_refuse(tmp_path) -> None:
    from hl_observer.ops.family_economic_job import record_family_economic_memory

    workspace = _workspace(tmp_path, full=False)
    with pytest.raises(RuntimeError, match="not FULL"):
        record_family_economic_memory(
            lab_root=tmp_path / "lab", workspace=workspace,
            suite="copy-vault-full", project_sha="a" * 40,
        )

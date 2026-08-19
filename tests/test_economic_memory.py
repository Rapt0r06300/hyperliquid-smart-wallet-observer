from __future__ import annotations

import json

import pytest

from hl_observer.datasets.economic_memory import (
    EconomicMemoryError,
    RELATIVE_PATH,
    SCHEMA,
    load_exact_proof,
    load_memory,
    proof_key,
    record_certified_proof,
)


def _common():
    return dict(
        project_sha="a" * 40,
        dataset_snapshot_sha256="b" * 64,
        config_sha256="c" * 64,
        suite="economic-full",
        runtime_proof_sha256="d" * 64,
        net_pnl_usd=4.25,
        analysis_complete=True,
        certified=True,
    )


def test_memory_is_partitioned_by_family_and_exact_provenance(tmp_path):
    copy = record_certified_proof(tmp_path, family="copy_vault", **_common())
    lead = record_certified_proof(tmp_path, family="lead_lag", **_common())
    assert copy["key"] != lead["key"]
    assert load_memory(tmp_path)["proof_count"] == 2
    loaded = load_exact_proof(
        tmp_path,
        project_sha="a" * 40,
        family="copy_vault",
        dataset_snapshot_sha256="b" * 64,
        config_sha256="c" * 64,
        suite="economic-full",
        runtime_proof_sha256="d" * 64,
    )
    assert loaded["net_pnl_usd"] == pytest.approx(4.25)


def test_memory_refuses_incomplete_stale_or_silent_overwrite(tmp_path):
    common = _common()
    record_certified_proof(tmp_path, family="copy_vault", **common)
    with pytest.raises(EconomicMemoryError, match="immutable"):
        record_certified_proof(
            tmp_path,
            family="copy_vault",
            **{**common, "runtime_proof_sha256": "e" * 64},
        )
    with pytest.raises(EconomicMemoryError, match="incomplete"):
        record_certified_proof(
            tmp_path,
            family="lead_lag",
            **{**common, "analysis_complete": False},
        )
    with pytest.raises(EconomicMemoryError, match="no certified proof"):
        load_exact_proof(
            tmp_path,
            project_sha="f" * 40,
            family="copy_vault",
            dataset_snapshot_sha256="b" * 64,
            config_sha256="c" * 64,
            suite="economic-full",
        )


def test_memory_refuses_below_target_even_with_certified_true(tmp_path):
    with pytest.raises(EconomicMemoryError, match="canonical target"):
        record_certified_proof(
            tmp_path,
            family="copy_vault",
            **{**_common(), "net_pnl_usd": 3.999999},
        )
    assert load_memory(tmp_path)["proofs"] == {}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), "not-a-number"])
def test_memory_refuses_non_finite_certified_net(tmp_path, bad):
    with pytest.raises(EconomicMemoryError, match="finite"):
        record_certified_proof(
            tmp_path,
            family="lead_lag",
            **{**_common(), "net_pnl_usd": bad},
        )


def test_load_exact_refuses_legacy_below_target_record(tmp_path):
    key = proof_key(
        project_sha="a" * 40,
        family="copy_vault",
        dataset_snapshot_sha256="b" * 64,
        config_sha256="c" * 64,
        suite="economic-full",
    )
    record = {
        "key": key,
        "project_sha": "a" * 40,
        "family": "copy_vault",
        "dataset_snapshot_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "suite": "economic-full",
        "runtime_proof_sha256": "d" * 64,
        "net_pnl_usd": 1.0,
        "analysis_complete": True,
        "certified": True,
        "paper_only": True,
        "real_execution": False,
    }
    path = tmp_path / RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "proofs": {key: record},
                "proof_count": 1,
                "paper_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EconomicMemoryError, match="canonical target"):
        load_exact_proof(
            tmp_path,
            project_sha="a" * 40,
            family="copy_vault",
            dataset_snapshot_sha256="b" * 64,
            config_sha256="c" * 64,
            suite="economic-full",
            runtime_proof_sha256="d" * 64,
        )

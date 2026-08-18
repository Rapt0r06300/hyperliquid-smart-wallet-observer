from __future__ import annotations

import pytest

from hl_observer.datasets.economic_memory import (
    EconomicMemoryError,
    load_exact_proof,
    load_memory,
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

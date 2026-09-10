import pytest

from hl_observer.simulation import vnext_promotion_protocol as protocol


def _candidate() -> dict[str, object]:
    manifest = protocol.build_freeze_manifest(
        family="lead_lag",
        freeze_candidate={"variant": "alpha"},
        dataset_fingerprint="d" * 64,
        config={"capital_usd": 1000.0, "paper_read_only": True},
        frozen_at_ms=1_000,
    )
    freeze_hash = str(manifest["freeze_hash"])
    return {
        "certification_status": "CERTIFICATION_READY",
        "freeze_manifest": manifest,
        "freeze_hash": freeze_hash,
        "observed_dataset_sha256": manifest["dataset_sha256"],
        "observed_config_sha256": manifest["config_sha256"],
        "post_freeze_oos_consumed": True,
        "consumed_freeze_hash": freeze_hash,
        "paper_read_only": True,
        "real_execution": False,
        "frozen_at_ms": 1_000,
        "temporal_windows": {
            "validation": {"start_ms": 1_100, "end_ms": 1_200},
            "oos": {"start_ms": 1_200, "end_ms": 1_300},
            "forward": {"start_ms": 1_300, "end_ms": 1_400},
            "placebo": {"start_ms": 1_400, "end_ms": 1_500},
        },
        "costs_complete": True,
        "liquidability_complete": True,
        "provenance_complete": True,
        "positions_flat": True,
        "economic_reconciliation_ok": True,
        "validation_without_recalibration": True,
        "temporal_disjointness_ok": True,
        "forward_post_freeze_complete": True,
        "placebo_complete": True,
    }


def test_certification_rejects_post_freeze_dataset_mutation() -> None:
    candidate = _candidate()
    candidate["observed_dataset_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="dataset fingerprint"):
        protocol.validate_certification_entry(candidate)


def test_certification_rejects_post_freeze_config_mutation() -> None:
    candidate = _candidate()
    candidate["observed_config_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="config fingerprint"):
        protocol.validate_certification_entry(candidate)


def test_certification_rejects_missing_observed_fingerprints() -> None:
    candidate = _candidate()
    candidate.pop("observed_dataset_sha256")
    candidate.pop("observed_config_sha256")
    with pytest.raises(ValueError, match="observed_dataset_sha256"):
        protocol.validate_certification_entry(candidate)

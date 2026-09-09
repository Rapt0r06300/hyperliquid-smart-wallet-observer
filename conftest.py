from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def seed_copy_vault_vnext_certification_for_explicit_fusion_contract(
    request: pytest.FixtureRequest,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seed the frozen Copy-Vault proof only for the fusion contract that expects an opening.

    H-T-24 made the legacy whitelist restrictive-only.  This integration test exercises the
    downstream fusion/persistence mechanics, so its pre-existing whitelist fixture is no longer
    sufficient by construction.  Keep production fail-closed and provide the second, real vNext
    gate only inside this exact test node.  Dedicated Copy-Vault gate tests continue to cover
    missing/invalid certification refusal paths.
    """

    if request.node.name != "test_fusion_status_route_runs_only_from_explicit_engine_input":
        return

    from hl_observer.signals import porte_copy_whitelist as copy_gate
    from hl_observer.simulation import vnext_promotion_protocol as protocol

    manifest = protocol.build_freeze_manifest(
        family="copy_vault",
        freeze_candidate={"variant": "ui-explicit-fusion-contract"},
        dataset_fingerprint="d" * 64,
        config={"capital_usd": 1000.0, "paper_read_only": True},
        frozen_at_ms=1_000,
    )
    freeze_hash = str(manifest["freeze_hash"])
    proof = {
        "certification_status": "CERTIFICATION_READY",
        "freeze_manifest": manifest,
        "freeze_hash": freeze_hash,
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
    certification_path = tmp_path / "copy_vault_vnext_certification.json"
    certification_path.write_text(
        json.dumps({"family": "copy_vault", "vnext_promotion": proof}),
        encoding="utf-8",
    )
    monkeypatch.setattr(copy_gate, "CHEMIN_CERTIFICATION_VNEXT", certification_path)

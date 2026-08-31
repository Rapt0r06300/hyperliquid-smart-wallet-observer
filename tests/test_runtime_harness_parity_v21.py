from __future__ import annotations

from copy import deepcopy

import pytest

from hl_observer.ops.self_hosted_control import (
    CONTROL_SCHEMA,
    audit_runtime_harness_parity,
    build_control_bundle,
    build_worker_request,
    render_runtime_harness_contract,
)

SHA = "a" * 40


def _control() -> dict[str, object]:
    return {
        "schema": CONTROL_SCHEMA,
        "job_id": "parity-v21",
        "suite": "economic-full",
        "mode": "economic",
        "download": False,
    }


def _views() -> tuple[dict[str, object], dict[str, object]]:
    request = build_worker_request(_control(), project_sha=SHA)
    return (
        render_runtime_harness_contract(request, harness="interactive"),
        render_runtime_harness_contract(request, harness="headless"),
    )


def test_interactif_et_headless_derivent_du_meme_contrat() -> None:
    interactive, headless = _views()
    receipt = audit_runtime_harness_parity(interactive, headless)

    assert receipt["ready"] is True
    assert receipt["issues"] == []
    assert interactive["contract"] == headless["contract"]
    assert interactive["canonical_contract_sha256"] == (
        headless["canonical_contract_sha256"]
    )
    contract = interactive["contract"]
    assert isinstance(contract, dict)
    assert contract["output_schema"] == {
        "live_status": "alina.autonomous_live_status.v1",
        "job_result": "alina.autonomous_research_result.v1",
        "compact_return": "alina.self_hosted_return.v1",
        "required_security_fields": {
            "paper_only": True,
            "real_execution": False,
        },
    }


@pytest.mark.parametrize(
    "surface",
    ("constraints", "tool_scope", "state_semantics", "output_schema"),
)
def test_toute_derive_semantique_est_refusee(surface: str) -> None:
    interactive, headless = _views()
    tampered = deepcopy(headless)
    contract = tampered["contract"]
    assert isinstance(contract, dict)
    selected = contract[surface]
    assert isinstance(selected, dict)
    selected["injected_drift"] = True

    receipt = audit_runtime_harness_parity(interactive, tampered)

    assert receipt["ready"] is False
    assert f"HARNESS_{surface.upper()}_DRIFT" in receipt["issues"]
    assert "HEADLESS_CONTRACT_HASH_MISMATCH" in receipt["issues"]


def test_bundle_expose_la_vue_reellement_selectionnee_et_la_parite() -> None:
    interactive_bundle = build_control_bundle(
        _control(), project_sha=SHA, harness="interactive"
    )
    headless_bundle = build_control_bundle(_control(), project_sha=SHA)

    assert interactive_bundle["runtime_contract"]["selected_harness"] == "interactive"
    assert headless_bundle["runtime_contract"]["selected_harness"] == "headless"
    assert headless_bundle["runtime_contract"]["parity_receipt"]["ready"] is True
    assert interactive_bundle["runtime_contract"]["interactive"]["contract"] == (
        headless_bundle["runtime_contract"]["headless"]["contract"]
    )


def test_harness_inconnu_est_refuse_avant_execution() -> None:
    with pytest.raises(ValueError, match="harness inconnu"):
        build_control_bundle(_control(), project_sha=SHA, harness="remote-shell")

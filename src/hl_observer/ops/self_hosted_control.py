from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.control_plane.typed_events import (
    ControlEventReplayLedger,
    build_typed_control_event,
    control_event_receipt,
)
from hl_observer.ops.autonomous_research_job import (
    CANONICAL_DATASET_REPOSITORY,
    CANONICAL_RELEASE_ID,
    request_digest,
)
from hl_observer.ops.autonomous_research_job import (
    SCHEMA as WORKER_SCHEMA,
)
from hl_observer.ops.autonomous_research_job_router import validate_request

CONTROL_SCHEMA = "alina.self_hosted_control.v1"
RUNTIME_CONTRACT_SCHEMA = "alina.runtime_contract.v1"
RUNTIME_HARNESS_VIEW_SCHEMA = "alina.runtime_harness_view.v1"
RUNTIME_PARITY_RECEIPT_SCHEMA = "alina.runtime_harness_parity_receipt.v1"
RUNTIME_HARNESSES = frozenset({"interactive", "headless"})
MAX_CYCLE_SECONDS = 18 * 60 * 60
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
ALLOWED_CONTROL_FIELDS = frozenset(
    {
        "schema",
        "job_id",
        "suite",
        "mode",
        "download",
        "max_download_gib",
        "stage_timeout_seconds",
        "cross_budget_s",
        "lead_history_sources",
        "force",
        "max_cycle_seconds",
        "requested_by",
        "note",
    }
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Commande illisible: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("La commande doit être un objet JSON.")
    return raw


def _strict_bool(raw: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} doit être un booléen JSON.")
    return value


def normalize_control(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("schema") != CONTROL_SCHEMA:
        raise ValueError(f"schema doit être {CONTROL_SCHEMA}")

    unknown = sorted(str(key) for key in raw if str(key) not in ALLOWED_CONTROL_FIELDS)
    if unknown:
        raise ValueError(
            "Champs de commande refusés (schéma fermé): " + ", ".join(unknown)
        )

    job_id = str(raw.get("job_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", job_id):
        raise ValueError("job_id invalide: 1-80 caractères alphanumériques, . _ - uniquement.")

    max_cycle_seconds = int(raw.get("max_cycle_seconds", MAX_CYCLE_SECONDS))
    if max_cycle_seconds < 60 or max_cycle_seconds > MAX_CYCLE_SECONDS:
        raise ValueError(f"max_cycle_seconds doit être compris entre 60 et {MAX_CYCLE_SECONDS}.")

    requested_by = str(raw.get("requested_by") or "GitHub").strip()[:120]
    note = str(raw.get("note") or "").strip()[:500]

    return {
        "schema": CONTROL_SCHEMA,
        "job_id": job_id,
        "suite": str(raw.get("suite") or "").strip(),
        "mode": str(raw.get("mode") or "").strip(),
        "download": _strict_bool(raw, "download", True),
        "max_download_gib": float(raw.get("max_download_gib", 20.0)),
        "stage_timeout_seconds": int(raw.get("stage_timeout_seconds", 3600)),
        "cross_budget_s": float(raw.get("cross_budget_s", 20.0)),
        "lead_history_sources": int(raw.get("lead_history_sources", 8)),
        "force": _strict_bool(raw, "force", False),
        "max_cycle_seconds": max_cycle_seconds,
        "requested_by": requested_by,
        "note": note,
    }


def build_worker_request(control: Mapping[str, Any], *, project_sha: str) -> dict[str, Any]:
    normalized = normalize_control(control)
    sha = str(project_sha).strip().lower()
    if not SHA_RE.fullmatch(sha):
        raise ValueError("project_sha doit être un SHA Git complet de 40 caractères hexadécimaux.")

    # Le plan de contrôle ne peut jamais demander un autre dépôt, une autre release,
    # une autre branche ou activer une exécution réelle. Ces valeurs sont imposées ici.
    worker = {
        "schema": WORKER_SCHEMA,
        "job_id": normalized["job_id"],
        "suite": normalized["suite"],
        "mode": normalized["mode"],
        "project_ref": "main",
        "project_sha": sha,
        "release_id": CANONICAL_RELEASE_ID,
        "dataset_repository": CANONICAL_DATASET_REPOSITORY,
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "download": normalized["download"],
        "max_download_gib": normalized["max_download_gib"],
        "stage_timeout_seconds": normalized["stage_timeout_seconds"],
        "cross_budget_s": normalized["cross_budget_s"],
        "lead_history_sources": normalized["lead_history_sources"],
    }
    return validate_request(worker)


def canonical_runtime_contract(worker_request: Mapping[str, Any]) -> dict[str, Any]:
    """Derive every harness invariant from the validated worker request."""

    request = validate_request(worker_request)
    return {
        "schema": RUNTIME_CONTRACT_SCHEMA,
        "workflow_id": "autonomous_research_worker",
        "request_digest": request_digest(request),
        "constraints": {
            "project_ref": request["project_ref"],
            "project_sha": request["project_sha"],
            "paper_only": request["paper_only"],
            "real_execution": request["real_execution"],
            "start_live_collection": request["start_live_collection"],
            "dataset_repository": request["dataset_repository"],
            "release_id": request["release_id"],
        },
        "tool_scope": {
            "capability": "RUN_PAPER_RESEARCH",
            "entrypoint": "hl_observer.ops.autonomous_research_job",
            "allowed_operations": [
                "read_local_datasets",
                "write_local_evidence",
                "download_canonical_dataset_if_requested",
            ],
            "forbidden_operations": [
                "arbitrary_shell",
                "external_order",
                "mainnet_execution",
                "private_key_access",
                "signature",
                "testnet_execution",
            ],
        },
        "state_semantics": {
            "authority": "typed_control_event",
            "idempotency_key": "job_id+request_digest+project_sha",
            "ledger": "append_only_single_use_control_event",
            "resume": "same_request_digest_and_project_sha_only",
            "writer": "single_worker",
        },
        "output_schema": {
            "live_status": "alina.autonomous_live_status.v1",
            "job_result": "alina.autonomous_research_result.v1",
            "compact_return": "alina.self_hosted_return.v1",
            "required_security_fields": {
                "paper_only": True,
                "real_execution": False,
            },
        },
    }


def render_runtime_harness_contract(
    worker_request: Mapping[str, Any], *, harness: str
) -> dict[str, Any]:
    """Render a harness view without granting the harness semantic authority."""

    normalized_harness = str(harness).strip().lower()
    if normalized_harness not in RUNTIME_HARNESSES:
        raise ValueError(f"harness inconnu: {harness}")
    canonical = canonical_runtime_contract(worker_request)
    canonical_sha256 = request_digest(canonical)
    return {
        "schema": RUNTIME_HARNESS_VIEW_SCHEMA,
        "harness": normalized_harness,
        "canonical_contract_sha256": canonical_sha256,
        "contract": canonical,
    }


def audit_runtime_harness_parity(
    interactive: Mapping[str, Any], headless: Mapping[str, Any]
) -> dict[str, Any]:
    """Fail closed when generated interactive/headless semantics drift."""

    issues: list[str] = []
    expected_harnesses = ((interactive, "interactive"), (headless, "headless"))
    contracts: list[Mapping[str, Any]] = []
    hashes: list[str] = []
    for view, expected_harness in expected_harnesses:
        if view.get("schema") != RUNTIME_HARNESS_VIEW_SCHEMA:
            issues.append(f"{expected_harness.upper()}_VIEW_SCHEMA_INVALID")
        if view.get("harness") != expected_harness:
            issues.append(f"{expected_harness.upper()}_HARNESS_INVALID")
        contract = view.get("contract")
        if not isinstance(contract, Mapping):
            issues.append(f"{expected_harness.upper()}_CONTRACT_MISSING")
            continue
        contracts.append(contract)
        actual_hash = request_digest(contract)
        declared_hash = str(view.get("canonical_contract_sha256") or "")
        hashes.append(actual_hash)
        if declared_hash != actual_hash:
            issues.append(f"{expected_harness.upper()}_CONTRACT_HASH_MISMATCH")
        if contract.get("schema") != RUNTIME_CONTRACT_SCHEMA:
            issues.append(f"{expected_harness.upper()}_CONTRACT_SCHEMA_INVALID")

    if len(contracts) == 2:
        for surface in (
            "constraints",
            "tool_scope",
            "state_semantics",
            "output_schema",
        ):
            if contracts[0].get(surface) != contracts[1].get(surface):
                issues.append(f"HARNESS_{surface.upper()}_DRIFT")
        if contracts[0] != contracts[1]:
            issues.append("HARNESS_CANONICAL_CONTRACT_DRIFT")
    canonical_hash = hashes[0] if len(hashes) == 2 and len(set(hashes)) == 1 else None
    body = {
        "schema": RUNTIME_PARITY_RECEIPT_SCHEMA,
        "ready": not issues,
        "issues": sorted(set(issues)),
        "canonical_contract_sha256": canonical_hash,
        "surfaces_compared": [
            "constraints",
            "tool_scope",
            "state_semantics",
            "output_schema",
        ],
    }
    return {**body, "receipt_sha256": request_digest(body)}


def build_control_bundle(
    control: Mapping[str, Any], *, project_sha: str, harness: str = "headless"
) -> dict[str, Any]:
    normalized = normalize_control(control)
    worker_request = build_worker_request(normalized, project_sha=project_sha)
    interactive_contract = render_runtime_harness_contract(
        worker_request, harness="interactive"
    )
    headless_contract = render_runtime_harness_contract(
        worker_request, harness="headless"
    )
    parity_receipt = audit_runtime_harness_parity(
        interactive_contract, headless_contract
    )
    if parity_receipt["ready"] is not True:
        raise RuntimeError("Dérive interactive/headless refusée.")
    normalized_harness = str(harness).strip().lower()
    if normalized_harness not in RUNTIME_HARNESSES:
        raise ValueError(f"harness inconnu: {harness}")
    typed_event = build_typed_control_event(
        event_type="RUN_RESEARCH_JOB",
        nonce=normalized["job_id"],
        source_identity=normalized["requested_by"],
        source_run_id=normalized["job_id"],
        state_version=str(project_sha).lower(),
        target="autonomous_research_worker",
        capability="RUN_PAPER_RESEARCH",
        payload=worker_request,
    )
    return {
        "schema": "alina.self_hosted_control_bundle.v1",
        "control": normalized,
        # The validated typed event is the authority.  This convenience copy is
        # byte-equivalent to its payload for the existing worker CLI.
        "worker_request": dict(typed_event.payload),
        "typed_control_event": typed_event.as_dict(),
        "typed_control_receipt": control_event_receipt(
            typed_event,
            decision="VALIDATED_NOT_CLAIMED",
        ),
        "runtime_contract": {
            "selected_harness": normalized_harness,
            "selected": (
                interactive_contract
                if normalized_harness == "interactive"
                else headless_contract
            ),
            "interactive": interactive_contract,
            "headless": headless_contract,
            "parity_receipt": parity_receipt,
        },
        "guard": {
            "max_cycle_seconds": normalized["max_cycle_seconds"],
            "force": normalized["force"],
        },
        "security": {
            "paper_only": True,
            "real_execution": False,
            "live_collection": False,
            "project_ref": "main",
            "project_sha": str(project_sha).lower(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Transforme une petite commande GitHub en requête worker HyperSmart sûre et reproductible."
    )
    parser.add_argument("--control", required=True)
    parser.add_argument("--project-sha", required=True)
    parser.add_argument("--worker-request", required=True)
    parser.add_argument("--bundle-output")
    parser.add_argument("--event-ledger")
    parser.add_argument("--harness", choices=sorted(RUNTIME_HARNESSES), default="headless")
    args = parser.parse_args(argv)

    control_path = Path(args.control).resolve()
    worker_path = Path(args.worker_request).resolve()
    bundle = build_control_bundle(
        _load_json(control_path), project_sha=args.project_sha, harness=args.harness
    )
    if args.event_ledger:
        event = build_typed_control_event(
            event_type=bundle["typed_control_event"]["event_type"],
            nonce=bundle["typed_control_event"]["nonce"],
            source_identity=bundle["typed_control_event"]["source_identity"],
            source_run_id=bundle["typed_control_event"]["source_run_id"],
            state_version=bundle["typed_control_event"]["state_version"],
            target=bundle["typed_control_event"]["target"],
            capability=bundle["typed_control_event"]["capability"],
            payload=bundle["typed_control_event"]["payload"],
        )
        bundle["typed_control_receipt"] = ControlEventReplayLedger(
            Path(args.event_ledger)
        ).claim(event)

    worker_path.parent.mkdir(parents=True, exist_ok=True)
    worker_path.write_text(
        json.dumps(bundle["worker_request"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.bundle_output:
        bundle_path = Path(args.bundle_output).resolve()
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        "ALINA_SELF_HOSTED_CONTROL_READY "
        f"job={bundle['control']['job_id']} suite={bundle['control']['suite']} "
        f"mode={bundle['control']['mode']} max_cycle={bundle['guard']['max_cycle_seconds']}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALLOWED_CONTROL_FIELDS",
    "CONTROL_SCHEMA",
    "MAX_CYCLE_SECONDS",
    "RUNTIME_CONTRACT_SCHEMA",
    "RUNTIME_HARNESSES",
    "RUNTIME_HARNESS_VIEW_SCHEMA",
    "RUNTIME_PARITY_RECEIPT_SCHEMA",
    "audit_runtime_harness_parity",
    "build_control_bundle",
    "build_worker_request",
    "canonical_runtime_contract",
    "normalize_control",
    "render_runtime_harness_contract",
]

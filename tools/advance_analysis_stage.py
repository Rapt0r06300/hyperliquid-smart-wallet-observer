#!/usr/bin/env python3
"""Monotonically advance ANALYZE stage in the durable Dataset V2 phase state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path


ORDER = ("DRAIN", "QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD", "DONE")


def _superseded_campaign_ids(rows):
    """Return explicitly superseded attempts only when replacement identity is exact."""
    by_id = {
        str(row.get("campaign_id")): row
        for row in rows
        if row.get("campaign_id")
    }
    identity_fields = (
        "creation_phase",
        "phase_epoch",
        "source_collection_epoch",
        "kind",
        "dataset_selection_id",
        "collection_cutoff_at_utc",
        "work_plan_sha256",
        "config_sha256",
    )
    superseded = set()
    for replacement in rows:
        if replacement.get("status") != "COMPLETE":
            continue
        declared = replacement.get("supersedes_campaign_ids")
        if not isinstance(declared, list):
            continue
        for campaign_id in declared:
            original = by_id.get(str(campaign_id))
            if not isinstance(original, dict):
                continue
            if all(original.get(key) == replacement.get(key) for key in identity_fields):
                superseded.add(str(campaign_id))
    return superseded


def _required_campaign_gate(rows, state, required_kinds):
    """Require every current-epoch campaign of a required kind to be COMPLETE."""
    superseded = _superseded_campaign_ids(rows)
    scoped = [
        row for row in rows
        if row.get("creation_phase") == "ANALYZE"
        and int(row.get("phase_epoch") or 0) == int(state["epoch"])
        and row.get("source_collection_epoch") == state.get("source_collection_epoch")
        and str(row.get("kind")) in required_kinds
        and str(row.get("campaign_id") or "") not in superseded
    ]
    observed = {
        str(row.get("kind"))
        for row in scoped
        if row.get("status") == "COMPLETE"
    }
    missing = sorted(required_kinds - observed)
    incomplete = sorted(
        str(row.get("campaign_id") or "<unknown>")
        for row in scoped
        if row.get("status") != "COMPLETE"
    )
    return missing, incomplete


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=ORDER, required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--expected-epoch", type=int, required=True)
    p.add_argument("--path", default="control/alina-phase.json")
    p.add_argument("--campaign-root", default="catalog/campaigns")
    p.add_argument("--receipt-dir", default="control/phase-receipts")
    p.add_argument("--gate-registry", default="control/analysis-stage-gates.json")
    a = p.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", a.request_id):
        raise SystemExit("invalid request id")
    path = Path(a.path)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("phase") != "ANALYZE":
        raise SystemExit("analysis stage requires ANALYZE phase")
    if int(state.get("epoch", 0)) != a.expected_epoch:
        raise SystemExit("stale phase epoch")
    current = str(state.get("analysis_stage") or "")
    if current not in ORDER:
        raise SystemExit("invalid current analysis stage")
    if ORDER.index(a.stage) < ORDER.index(current):
        raise SystemExit(f"analysis stage regression: {current}->{a.stage}")
    if ORDER.index(a.stage) > ORDER.index(current) + 1:
        raise SystemExit(f"analysis stage skip is forbidden: {current}->{a.stage}")
    gates = json.loads(Path(a.gate_registry).read_text(encoding="utf-8"))
    if gates.get("paper_only") is not True or gates.get("read_only") is not True or gates.get("real_execution") is not False:
        raise SystemExit("unsafe analysis gate registry")
    gate = gates.get("stages", {}).get(a.stage)
    if not isinstance(gate, dict):
        raise SystemExit(f"missing gate for stage {a.stage}")
    for required in gate.get("required_files", []):
        if not Path(required).is_file():
            raise SystemExit(f"stage gate missing required file: {required}")
    required_coverage = gate.get("required_coverage") or {}
    if required_coverage:
        coverage_path = Path(
            gate.get("coverage_receipt", "catalog/DATASET_HEALTH_RECEIPT.json")
        )
        health = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage = health.get("coverage") if isinstance(health.get("coverage"), dict) else {}
        for key, requirement in required_coverage.items():
            value = coverage.get(key)
            if isinstance(requirement, dict) and "min" in requirement:
                if not isinstance(value, (int, float)) or value < requirement["min"]:
                    raise SystemExit(f"stage gate coverage {key} below minimum")
            elif value != requirement:
                raise SystemExit(f"stage gate coverage {key} is not proven")
    required_watchdog_status = gate.get("required_watchdog_status")
    if required_watchdog_status:
        watchdog = json.loads(Path("catalog/CAMPAIGN_WATCHDOG_RECEIPT.json").read_text(encoding="utf-8"))
        if watchdog.get("watchdog_status") != required_watchdog_status:
            raise SystemExit("stage gate watchdog status is not proven")
    required_resilience_status = gate.get("required_resilience_status")
    if required_resilience_status:
        resilience = json.loads(Path("catalog/CAMPAIGN_RESILIENCE_RECEIPT.json").read_text(encoding="utf-8"))
        if resilience.get("status") != required_resilience_status:
            raise SystemExit("stage gate resilience status is not proven")
    required_global_flags = gate.get("required_global_flags") or {}
    if required_global_flags:
        closure = json.loads(Path("catalog/GLOBAL_IMPLEMENTATION_CLOSURE.json").read_text(encoding="utf-8"))
        for key, expected in required_global_flags.items():
            if closure.get(key) is not expected:
                raise SystemExit(f"stage gate global flag {key} is not proven")
    required_kinds = set(gate.get("required_campaign_kinds", []))
    if required_kinds:
        rows = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(Path(a.campaign_root).glob("*.json"))
        ]
        missing, incomplete = _required_campaign_gate(rows, state, required_kinds)
        if missing:
            raise SystemExit(f"stage gate missing terminal campaign kinds: {missing}")
        if incomplete:
            raise SystemExit(
                "stage gate has non-complete current campaigns: " + ",".join(incomplete)
            )
    if current == "DRAIN" and a.stage != "DRAIN":
        source_epoch = int(state.get("source_collection_epoch") or 0)
        active = {"PENDING", "RUNNING", "CONTINUATION_REQUIRED", "STUCK"}
        for manifest_path in sorted(Path(a.campaign_root).glob("*.json")):
            row = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                row.get("creation_phase") == "COLLECT"
                and int(row.get("phase_epoch") or 0) == source_epoch
                and row.get("status") in active
            ):
                raise SystemExit(f"DRAIN barrier not closed: {manifest_path.name}")
    terminal_rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(a.campaign_root).glob("*.json"))
        if path.is_file()
    ]
    frozen_rows = [
        row for row in terminal_rows
        if row.get("creation_phase") == "ANALYZE"
        and int(row.get("phase_epoch") or 0) == int(state["epoch"])
        and row.get("source_collection_epoch") == state.get("source_collection_epoch")
    ]
    selection_ids = sorted({
        str(row.get("dataset_selection_id"))
        for row in frozen_rows
        if row.get("dataset_selection_id")
    })
    code_shas = sorted({
        str(row.get("code_sha"))
        for row in frozen_rows
        if row.get("code_sha")
    })
    checkpoint_ids = sorted({
        str((row.get("cursor") or {}).get("checkpoint_id"))
        for row in frozen_rows
        if isinstance(row.get("cursor"), dict) and row["cursor"].get("checkpoint_id")
    })
    artifact_ids = sorted({
        str(value)
        for row in frozen_rows
        for value in (
            row.get("release_tag"),
            row.get("evidence_tag"),
            (row.get("cursor") or {}).get("artifact_id")
            if isinstance(row.get("cursor"), dict)
            else None,
        )
        if value
    })
    if state.get("request_id") != a.request_id and a.stage == current:
        raise SystemExit("stage identity conflict")
    if a.stage != current:
        previous = dict(state)
        state = {**state, "analysis_stage": a.stage, "request_id": a.request_id}
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    else:
        previous = dict(state)
    receipt = {
        "schema": "alina.analysis_stage_receipt.v1",
        "request_id": a.request_id,
        "phase": "ANALYZE",
        "epoch": a.expected_epoch,
        "previous_stage": previous.get("analysis_stage"),
        "new_stage": state.get("analysis_stage"),
        "state_digest": hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "input_selection_ids": selection_ids,
        "input_selection_digest": hashlib.sha256(
            json.dumps(selection_ids, separators=(",", ":")).encode()
        ).hexdigest() if selection_ids else None,
        "code_shas": code_shas,
        "config_hash": hashlib.sha256(
            Path(a.gate_registry).read_bytes()
        ).hexdigest(),
        "checkpoint_ids": checkpoint_ids,
        "output_artifact_ids": artifact_ids,
        "resume_cursor_present": any(
            isinstance(row.get("cursor"), dict) and bool(row.get("cursor"))
            for row in frozen_rows
        ),
        "contract_status": (
            "COMPLETE"
            if selection_ids and code_shas and checkpoint_ids and artifact_ids
            else "INCOMPLETE_EVIDENCE"
        ),
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    receipt_path = Path(a.receipt_dir) / (a.request_id + "-stage.json")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        old_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if old_receipt != receipt:
            raise SystemExit("analysis stage receipt identity conflict")
    else:
        temporary_receipt = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
        temporary_receipt.write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_receipt, receipt_path)
    print(json.dumps(state, sort_keys=True))


if __name__ == "__main__":
    main()

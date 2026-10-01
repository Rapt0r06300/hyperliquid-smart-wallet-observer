#!/usr/bin/env python3
"""Write an immutable receipt for one durable campaign publication."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--campaign-id", required=True)
    p.add_argument("--unit-id", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--phase", required=True)
    p.add_argument("--phase-epoch", required=True, type=int)
    p.add_argument("--code-sha", required=True)
    p.add_argument("--dataset-generation", required=True)
    p.add_argument("--source-collection-epoch")
    p.add_argument("--collection-cutoff-at-utc")
    p.add_argument("--dataset-selection-id")
    p.add_argument("--checkpoint-id")
    p.add_argument("--release-tag")
    p.add_argument("--evidence-tag")
    p.add_argument("--result", required=True)
    p.add_argument("--alina-head", default="")
    p.add_argument("--dataset-head", default="")
    p.add_argument("--manifest-sha256", default="")
    p.add_argument("--publication-state", default="RELEASE_AND_RECEIPT_WRITTEN")
    p.add_argument("--output", default="")
    a = p.parse_args()

    if not re.fullmatch(r"[0-9a-f]{40}", a.code_sha):
        raise SystemExit("code_sha must be a commit SHA")
    if a.phase not in {"COLLECT", "ANALYZE"} or a.phase_epoch < 1:
        raise SystemExit("invalid phase identity")
    if a.phase == "ANALYZE" and (
        a.source_collection_epoch in (None, "")
        or a.collection_cutoff_at_utc in (None, "")
        or a.dataset_selection_id in (None, "")
    ):
        raise SystemExit("analysis publication requires frozen selection identity")

    result = json.loads(Path(a.result).read_text(encoding="utf-8"))
    payload = result.get("payload") if isinstance(result, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    receipt = {
        "schema": "alina.publication_receipt.v2",
        "receipt_id": f"{a.campaign_id}:u{a.unit_id}",
        "campaign_id": a.campaign_id,
        "unit_id": a.unit_id,
        "kind": a.kind,
        "status": a.status,
        "phase": a.phase,
        "phase_epoch": a.phase_epoch,
        "code_sha": a.code_sha,
        "dataset_generation": a.dataset_generation,
        "source_collection_epoch": (
            int(a.source_collection_epoch)
            if a.source_collection_epoch not in (None, "")
            else None
        ),
        "collection_cutoff_at_utc": a.collection_cutoff_at_utc or None,
        "dataset_selection_id": a.dataset_selection_id or None,
        "checkpoint_id": a.checkpoint_id or None,
        "analysis_stage": payload.get("analysis_stage"),
        "collection_plan_sha256": payload.get("collection_plan_sha256"),
        "universe_discovery_required": payload.get("universe_discovery_required"),
        "release_tag": a.release_tag or None,
        "evidence_tag": a.evidence_tag or None,
        "result_sha256": hashlib.sha256(canonical(result).encode()).hexdigest(),
        "payload_digest": hashlib.sha256(canonical(payload).encode()).hexdigest(),
        "alina_head": a.alina_head or None,
        "dataset_head": a.dataset_head or None,
        "manifest_sha256": a.manifest_sha256 or None,
        "publication_state": a.publication_state,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    target = Path(a.output or f"catalog/receipts/{a.campaign_id}-u{a.unit_id}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        old = json.loads(target.read_text(encoding="utf-8"))
        stable = dict(receipt)
        stable.pop("recorded_at_utc", None)
        previous = dict(old)
        previous.pop("recorded_at_utc", None)
        if stable != previous:
            raise SystemExit("publication receipt identity conflict")
        return
    target.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

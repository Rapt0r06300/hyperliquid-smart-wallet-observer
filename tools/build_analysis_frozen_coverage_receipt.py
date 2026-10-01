#!/usr/bin/env python3
"""Build an epoch-bound exact-coverage receipt for the frozen analysis index."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


EXACT_KEYS = (
    "valid_record_count_exact",
    "unique_record_count_exact",
    "trade_count_exact",
    "unique_trade_count_exact",
    "uncompressed_bytes_exact",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _git(root: Path, *args: str, text: bool = True):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def _historical_bytes(root: Path, commit: str, path: str) -> bytes:
    return _git(root, "show", f"{commit}:{path}", text=False)


def _replay_materialization_campaign(root: Path, phase: Mapping[str, Any]) -> tuple[dict, str]:
    matches = []
    for path in sorted((root / "catalog/campaigns").glob("*.json")):
        row = _load(path)
        if (
            row.get("schema_version") == "alina.resumable_campaign.v2"
            and row.get("creation_phase") == "ANALYZE"
            and row.get("kind") == "replay"
            and row.get("status") == "COMPLETE"
            and row.get("phase_epoch") == phase.get("epoch")
            and row.get("source_collection_epoch") == phase.get("source_collection_epoch")
            and row.get("collection_cutoff_at_utc") == phase.get("collection_cutoff_at_utc")
            and row.get("paper_only") is True
            and row.get("read_only") is True
            and row.get("real_execution") is False
        ):
            result = (row.get("completed_units") or {}).get("0", {}).get("result") or {}
            stdout = str(result.get("stdout") or "")
            if '"index_sha256"' in stdout and '"dataset_selection_id"' in stdout:
                matches.append((row, stdout))
    if len(matches) != 1:
        raise SystemExit(f"expected one completed replay materialization campaign, found {len(matches)}")
    return matches[0]


def build_receipt(root: Path) -> dict[str, Any]:
    phase = _load(root / "control/alina-phase.json")
    if phase.get("phase") != "ANALYZE":
        raise SystemExit("frozen coverage requires ANALYZE phase")
    cutoff = str(phase.get("collection_cutoff_at_utc") or "")
    if not cutoff.endswith("Z"):
        raise SystemExit("analysis cutoff is not canonical UTC")

    campaign, stdout = _replay_materialization_campaign(root, phase)
    index_matches = re.findall(r'"index_sha256":\s*"([0-9a-f]{64})"', stdout)
    selection_matches = re.findall(r'"dataset_selection_id":\s*"([0-9a-f]{64})"', stdout)
    safe_matches = re.findall(r'"safe_shards":\s*([0-9]+)', stdout)
    event_matches = re.findall(r'"events":\s*([0-9]+)', stdout)
    if not index_matches or not selection_matches:
        raise SystemExit("replay materialization provenance is incomplete")
    index_sha256 = index_matches[-1]
    selection_id = selection_matches[-1]
    if selection_id != campaign.get("dataset_selection_id"):
        raise SystemExit("replay selection binding mismatch")
    expected_selection = hashlib.sha256(
        f"{phase['source_collection_epoch']}|{cutoff}|{index_sha256}".encode()
    ).hexdigest()
    if expected_selection != selection_id:
        raise SystemExit("frozen index does not derive the campaign selection id")

    evidence_commit = _git(
        root,
        "log",
        "-1",
        "--format=%H",
        f"--before={cutoff}",
        "--",
        "catalog/DATASET_HEALTH_RECEIPT.json",
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", evidence_commit):
        raise SystemExit("no historical health receipt exists before the analysis cutoff")
    _git(root, "merge-base", "--is-ancestor", evidence_commit, "HEAD")
    frozen_index = _historical_bytes(root, evidence_commit, "catalog/DATA_INDEX.json")
    if hashlib.sha256(frozen_index).hexdigest() != index_sha256:
        raise SystemExit("historical health receipt is not bound to the replay index")

    health_bytes = _historical_bytes(
        root, evidence_commit, "catalog/DATASET_HEALTH_RECEIPT.json"
    )
    health = json.loads(health_bytes)
    stored_health_digest = str(health.get("receipt_digest") or "")
    health_body = dict(health)
    health_body.pop("receipt_digest", None)
    if _digest(health_body) != stored_health_digest:
        raise SystemExit("historical health receipt digest is invalid")
    coverage = health.get("coverage")
    if not isinstance(coverage, dict) or not all(coverage.get(key) is True for key in EXACT_KEYS):
        raise SystemExit("frozen index exact coverage is not proven")

    dataset_commit = str(health.get("dataset_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", dataset_commit):
        raise SystemExit("historical health receipt dataset commit is invalid")
    _git(root, "merge-base", "--is-ancestor", dataset_commit, evidence_commit)
    health_blob = _git(
        root,
        "rev-parse",
        f"{evidence_commit}:catalog/DATASET_HEALTH_RECEIPT.json",
    ).strip()

    body = {
        "schema": "alina.analysis_frozen_coverage_receipt.v1",
        "generated_at_utc": campaign.get("updated_at"),
        "phase_epoch": phase.get("epoch"),
        "source_collection_epoch": phase.get("source_collection_epoch"),
        "collection_cutoff_at_utc": cutoff,
        "dataset_selection_id": selection_id,
        "index_sha256": index_sha256,
        "replay_campaign_id": campaign.get("campaign_id"),
        "replay_terminal_evidence_digest": campaign.get("terminal_evidence_digest"),
        "replay_events": int(event_matches[-1]) if event_matches else None,
        "replay_safe_shards": int(safe_matches[-1]) if safe_matches else None,
        "health_evidence_commit": evidence_commit,
        "health_evidence_blob": health_blob,
        "health_receipt_digest": stored_health_digest,
        "health_dataset_commit": dataset_commit,
        "coverage": {
            **{key: coverage.get(key) for key in EXACT_KEYS},
            "replayable_shards": coverage.get("replayable_shards"),
        },
        "replayable_shards": coverage.get("replayable_shards"),
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    body["receipt_digest"] = _digest(body)
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--output", default="catalog/ANALYSIS_FROZEN_COVERAGE_RECEIPT.json"
    )
    args = parser.parse_args()
    root = Path(args.root)
    receipt = build_receipt(root)
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "receipt_digest": receipt["receipt_digest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

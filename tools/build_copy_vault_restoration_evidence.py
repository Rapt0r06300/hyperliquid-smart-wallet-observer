"""Build a fail-closed H-T95 restoration-report evidence record.

This adapter consumes the real ``RESTORE_REPORT.json`` emitted by the
read-only restore flow.  It never reconstructs a snapshot, fills missing
fields, or upgrades an incomplete report.  The resulting record is suitable
for the Copy-Vault closure matrix and retains the source report digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA = "hypersmart.copy_vault_restoration_evidence.v1"
RESTORE_SCHEMA = "alina.full_restore_report.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value.lower()))


def _git_sha(value: object) -> bool:
    return isinstance(value, str) and bool(_GIT_SHA_RE.fullmatch(value.lower()))


def build_evidence(report: dict[str, Any], *, source_report_sha256: str, head_sha: str, source: str) -> dict[str, Any]:
    """Derive one evidence record from a real restore report without inference."""

    missing: list[str] = []

    def require(path: str, predicate: Any) -> Any:
        current: Any = report
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                missing.append(path)
                return None
            current = current[part]
        if not predicate(current):
            missing.append(path)
        return current

    require("schema", lambda value: value == RESTORE_SCHEMA)
    require("status", lambda value: value == "REPLAY_READY_COMPLETE")
    require("read_only", lambda value: value is True)
    require("real_execution", lambda value: value is False)
    require("restore_complete", lambda value: value is True)
    require("replay_ready_complete", lambda value: value is True)
    require("all_source_assets_accounted_for", lambda value: value is True)
    require("source_byte_parity", lambda value: value is True)
    require("source_destination_match", lambda value: value is True)
    require("verification_failures", lambda value: value == 0)
    require("unverified_source_asset_count", lambda value: value == 0)
    require("failed_verification_source_bytes", lambda value: value == 0)
    require("missing_asset_bytes", lambda value: value == 0)
    require("source_inventory_sha256", _sha256)
    if not _sha256(source_report_sha256):
        missing.append("source_report_sha256")
    if not _git_sha(head_sha):
        missing.append("head_sha")

    missing = list(dict.fromkeys(missing))
    verified = not missing
    claims = {
        "restore_verified": verified,
        "replayed_sha256_match": verified,
        "restoration_receipt_present": report.get("schema") == RESTORE_SCHEMA,
        "source_report_untouched": True,
    }
    if not verified:
        claims = {key: False for key in claims}

    return {
        "schema": SCHEMA,
        "kind": "restoration_report",
        "source": source,
        "head_sha": head_sha,
        "run_id": f"restore-report:{source_report_sha256}",
        "evidence_status": "VERIFIED" if verified else "NOT_PROVEN",
        "paper_read_only": report.get("read_only") is True,
        "real_execution": report.get("real_execution") is True,
        "source_report_sha256": source_report_sha256,
        "restore_report_schema": report.get("schema"),
        "restore_report_status": report.get("status"),
        "claims": claims,
        "unresolved": missing,
        "source_inventory_sha256": report.get("source_inventory_sha256"),
        "verified_asset_count": report.get("verified_asset_count"),
        "verified_asset_bytes": report.get("verified_asset_bytes"),
        "restored_volume_bytes": report.get("restored_volume_bytes"),
    }


def build_from_path(report_path: Path, *, head_sha: str) -> dict[str, Any]:
    raw = report_path.read_bytes()
    try:
        report = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid restore report: {report_path}") from exc
    if not isinstance(report, dict):
        raise ValueError("restore report must be a JSON object")
    return build_evidence(
        report,
        source_report_sha256=_sha256_bytes(raw),
        head_sha=head_sha,
        source=str(report_path.resolve()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        evidence = build_from_path(args.report, head_sha=args.head_sha)
    except (OSError, ValueError) as exc:
        print(f"NOT_PROVEN: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps([evidence], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["evidence_status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Report verified progress for the local 3120-task roadmap.

This is a tracker only.  It never infers completion from source text, files,
commits, or a green test unrelated to a task receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DISALLOWED = {"QUEUED", "PENDING", "CANCELLED", "FAILED", "PARTIAL"}


def load_receipts(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    receipts: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        task_id = str(value.get("task_id", ""))
        if not task_id:
            raise ValueError(f"receipt line {line_number} has no task_id")
        receipts[task_id] = value
    return receipts


def _file_set_fingerprint(files: list[str], hashes: dict[str, str]) -> str:
    payload = "\n".join(f"{name}\0{hashes[name].lower()}" for name in files)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def receipt_is_verified(
    receipt: dict[str, Any], expected_sha: str | None, root: Path
) -> bool:
    verdict = str(receipt.get("verdict", "")).upper()
    run_status = str(receipt.get("run_status", "")).upper()
    sha = str(receipt.get("sha", "")).lower()
    command = str(receipt.get("command", "")).strip()
    evidence = receipt.get("evidence")
    exit_code = receipt.get("exit_code")
    files = receipt.get("files")
    file_sha256 = receipt.get("file_sha256")
    file_hashes_match = isinstance(files, list) and isinstance(file_sha256, dict)
    if file_hashes_match:
        try:
            current_hashes = {
                str(name): hashlib.sha256(
                    (root / str(name)).read_bytes()
                ).hexdigest()
                for name in files
            }
            file_hashes_match = (
                set(current_hashes) == set(file_sha256)
                and all(
                    current_hashes[name].lower() == str(file_sha256[name]).lower()
                    for name in current_hashes
                )
                and _file_set_fingerprint([str(name) for name in files], current_hashes)
                == sha
            )
        except (OSError, TypeError, ValueError):
            file_hashes_match = False
    return (
        verdict == "VERIFIED_DONE"
        and run_status not in DISALLOWED
        and (expected_sha is None or sha == expected_sha.lower())
        and bool(SHA_RE.fullmatch(sha))
        and bool(command)
        and exit_code == 0
        and isinstance(evidence, list)
        and bool(evidence)
        and file_hashes_match
    )


def report(
    manifest_path: Path,
    receipt_path: Path,
    expected_sha: str | None,
    root: Path,
) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest_path.name.endswith(".manifest.json"):
        raise ValueError("--manifest must end with .manifest.json")
    full_index_path = manifest_path.with_name(
        manifest_path.name.removesuffix(".manifest.json") + ".json"
    )
    tasks = json.loads(full_index_path.read_text(encoding="utf-8"))["tasks"]
    receipts = load_receipts(receipt_path)
    verified_ids = {
        task_id
        for task_id, receipt in receipts.items()
        if receipt_is_verified(receipt, expected_sha, root)
    }
    known_ids = {str(task["id"]) for task in tasks}
    verified_ids &= known_ids
    total = len(tasks)
    verified = len(verified_ids)
    return {
        "roadmap_id": payload["roadmap_id"],
        "source_sha256": payload["source_sha256"],
        "expected_code_sha": expected_sha,
        "total": total,
        "verified_done": verified,
        "percent": round(100.0 * verified / total, 2) if total else 0.0,
        "closure_allowed": verified == total and total > 0,
        "receipts_file": str(receipt_path),
        "unknown_receipt_ids": sorted(set(receipts) - known_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("docs/roadmap/ALINA_ROADMAP_3120.manifest.json"))
    parser.add_argument("--receipts", type=Path, default=Path("runtime/roadmap/ALINA_ROADMAP_3120.receipts.jsonl"))
    parser.add_argument(
        "--code-sha",
        help="optional exact 40-character fingerprint required for every receipt",
    )
    args = parser.parse_args()
    if args.code_sha and not SHA_RE.fullmatch(args.code_sha.lower()):
        parser.error("--code-sha must be exactly 40 lowercase hexadecimal characters")
    result = report(
        args.manifest,
        args.receipts,
        args.code_sha.lower() if args.code_sha else None,
        Path.cwd(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

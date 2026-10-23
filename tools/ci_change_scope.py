"""Scope rapid CI checks without treating dataset-only commits as code releases.

All source/config/workflow changes run full CI. Only known catalog data formats
qualify for a fast, fail-closed content verification on the exact push SHA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}")
_DATA_EXTENSIONS = frozenset({".json", ".jsonl", ".csv", ".txt", ".md", ".sha256"})
_REQUIRED_CATALOG = frozenset({
    "catalog/DATA_INDEX.json",
    "catalog/DATA_METRICS.json",
    "catalog/DATASET_HEALTH_RECEIPT.json",
})


def classify_paths(paths: list[str] | None) -> str:
    """Unknown/empty history and any executable or configuration change need full CI."""
    if not paths:
        return "source"
    for path in paths:
        p = Path(path)
        if not path.startswith("catalog/") or p.suffix.lower() not in _DATA_EXTENSIONS:
            return "source"
        if p.is_absolute() or ".." in p.parts:
            return "source"
    return "catalog"


def changed_paths(root: Path, before: str, head: str) -> list[str] | None:
    """Fail closed on unavailable history, including all-zero push baselines."""
    if not _SHA.fullmatch(before) or not _SHA.fullmatch(head) or before == "0" * 40:
        return None
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", before, head],
            cwd=root, capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def verify_catalog_changes(root: Path, paths: list[str]) -> None:
    """Data-only must still parse and preserve critical immutable receipts."""
    for rel in paths:
        path = root / rel
        if not path.is_file():
            if rel in _REQUIRED_CATALOG:
                raise ValueError(f"CRITICAL_CATALOG_FILE_MISSING:{rel}")
            continue  # A purged non-critical catalog receipt is not fabricated anew.
        if path.stat().st_size >= 99_000_000:
            raise ValueError(f"CATALOG_GITHUB_BLOB_LIMIT:{rel}")
        if path.suffix.lower() == ".jsonl":
            try:
                with path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        if line.strip():
                            json.loads(line)
            except (OSError, UnicodeError, ValueError) as exc:
                raise ValueError(f"INVALID_CATALOG_JSONL:{rel}") from exc
            continue
        if path.suffix.lower() != ".json":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"INVALID_CATALOG_JSON:{rel}") from exc
        if rel.startswith("catalog/campaigns/"):
            if not isinstance(value, dict) or any((
                value.get("paper_only") is not True,
                value.get("read_only") is not True,
                value.get("real_execution") is not False,
            )):
                raise ValueError(f"UNSAFE_CATALOG_CAMPAIGN:{rel}")
        if rel == "catalog/DATASET_HEALTH_RECEIPT.json":
            if not isinstance(value, dict) or value.get("schema_version") not in {
                "alina.dataset_health_receipt.v1",
                "alina.dataset_health_receipt.v2",
            }:
                raise ValueError("UNKNOWN_DATASET_HEALTH_SCHEMA")
            expected = value.get("receipt_digest")
            unsigned = dict(value)
            unsigned.pop("receipt_digest", None)
            digest = hashlib.sha256(json.dumps(
                unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode()).hexdigest()
            if not isinstance(expected, str) or digest != expected:
                raise ValueError("DATASET_HEALTH_DIGEST_MISMATCH")

    if any(name in paths for name in ("catalog/DATA_INDEX.json", "catalog/DATA_METRICS.json")):
        try:
            from tools.build_catalog_metrics import verify_metrics_source
        except ModuleNotFoundError:  # direct tools/ invocation before editable install
            from build_catalog_metrics import verify_metrics_source

        verify_metrics_source(
            root / "catalog/DATA_INDEX.json",
            root / "catalog/DATA_METRICS.json",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    paths = changed_paths(args.root, args.before, args.head)
    mode = classify_paths(paths)
    if mode == "catalog":
        verify_catalog_changes(args.root, paths or [])
    print(f"CI_CHANGE_SCOPE={mode} changed_files={len(paths or [])}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"mode={mode}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

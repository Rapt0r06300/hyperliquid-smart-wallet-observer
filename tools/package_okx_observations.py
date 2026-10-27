#!/usr/bin/env python3
"""Package research-only OKX observation JSON with a SHA-256 inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_archive(report_root: Path, archive_path: Path) -> dict[str, Any]:
    root = report_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("report root must be a directory")
    files = sorted(path for path in root.rglob("*.json") if path.is_file() and not path.is_symlink())
    if not files:
        raise ValueError("no JSON observation data to package")
    entries = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        if relative.startswith("../") or "\\" in relative:
            raise ValueError("unsafe report path")
        payload = path.read_bytes()
        entries.append({
            "path": relative,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    phase_epochs: set[int] = set()
    for path in files:
        if path.name != "RAPPORT.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        epoch = payload.get("phase_epoch") if isinstance(payload, dict) else None
        if epoch is not None:
            if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
                raise ValueError("observation report has an invalid phase epoch")
            phase_epochs.add(epoch)
    if len(phase_epochs) > 1:
        raise ValueError("reports from multiple phase epochs cannot share one archive")
    manifest = {
        "schema_version": "alina.okx_observation_archive.v1",
        "research_only": True,
        "safe_replay_evidence": False,
        "economic_proof_ready": False,
        "source_repository": os.getenv("GITHUB_REPOSITORY", "local"),
        "source_commit": os.getenv("GITHUB_SHA"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "phase_epoch": next(iter(phase_epochs)) if phase_epochs else None,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": entries,
        "file_count": len(entries),
    }
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, entry in zip(files, entries, strict=True):
            archive.write(path, entry["path"])
        archive.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_root", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    manifest = build_archive(args.report_root, args.archive)
    print(json.dumps({"archive": str(args.archive), "file_count": manifest["file_count"], "research_only": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

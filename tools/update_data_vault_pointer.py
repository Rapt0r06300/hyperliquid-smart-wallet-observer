from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA = "alina.data_vault.pointer.v1"


def build_pointer(
    published: dict[str, Any],
    summary: dict[str, Any],
    *,
    index_asset_name: str = "VAULT_FILE_INDEX.json.gz",
) -> dict[str, Any]:
    assets = published.get("assets")
    if not isinstance(assets, list):
        raise ValueError("published release has no assets list")

    index_asset = None
    manifest_asset = None
    summary_asset = None
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "")
        if name == index_asset_name:
            index_asset = raw
        elif name == "VAULT_SNAPSHOT_MANIFEST.json.gz":
            manifest_asset = raw
        elif name == "VAULT_SUMMARY.json":
            summary_asset = raw

    if index_asset is None:
        raise ValueError("published release is missing VAULT_FILE_INDEX.json.gz")

    snapshot_id = str(published.get("snapshot_id") or summary.get("snapshot_id") or "")
    tag = str(published.get("tag") or summary.get("release_tag") or "")
    release_id = int(published.get("release_id") or 0)
    if not snapshot_id or not tag or release_id <= 0:
        raise ValueError("published release identity is incomplete")

    return {
        "schema": SCHEMA,
        "repository": str(published.get("repository") or ""),
        "latest_snapshot_id": snapshot_id,
        "latest_release_id": release_id,
        "latest_release_tag": tag,
        "published_at_utc": published.get("published_at_utc"),
        "release_url": published.get("html_url"),
        "index_asset": index_asset,
        "snapshot_manifest_asset": manifest_asset,
        "summary_asset": summary_asset,
        "snapshot_summary": {
            "candidate_files": int(summary.get("candidate_files") or 0),
            "candidate_bytes": int(summary.get("candidate_bytes") or 0),
            "current_index_files": int(summary.get("current_index_files") or 0),
            "present_local_files": int(summary.get("present_local_files") or 0),
            "archived_deleted_files": int(summary.get("archived_deleted_files") or 0),
            "changed_files": int(summary.get("changed_files") or 0),
            "changed_bytes": int(summary.get("changed_bytes") or 0),
            "deleted_count": int(summary.get("deleted_count") or 0),
            "unstable_count": int(summary.get("unstable_count") or 0),
            "secret_skip_count": int(summary.get("secret_skip_count") or 0),
            "read_error_count": int(summary.get("read_error_count") or 0),
            "data_asset_count": int(summary.get("data_asset_count") or 0),
            "data_asset_bytes": int(summary.get("data_asset_bytes") or 0),
        },
        "paper_only": True,
        "real_execution": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--published", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        published = json.loads(args.published.read_text(encoding="utf-8"))
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        pointer = build_pointer(published, summary)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(pointer, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps({"ok": True, **pointer}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Explicit, fail-closed migration of resumable campaign manifests to V2.

The V1 source is first preserved byte-for-byte in the durable history namespace.
The V2 lineage records the preserved V1 digest/path so migration never erases
historical truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _preserve_v1(*, history_dir: Path, source_path: Path, raw_text: str, digest: str) -> Path:
    target = history_dir / f"{source_path.stem}.v1.{digest}.json"
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing != raw_text:
            raise SystemExit(f"{target}: historical V1 collision")
        return target
    _atomic_write(target, raw_text)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-dir", default="catalog/campaigns")
    parser.add_argument("--history-dir", default="catalog/campaign-history")
    parser.add_argument("--phase", choices=["COLLECT", "ANALYZE"], required=True)
    parser.add_argument("--phase-epoch", type=int, required=True)
    parser.add_argument("--source-collection-epoch", type=int)
    parser.add_argument("--collection-cutoff-at-utc")
    parser.add_argument("--dataset-selection-id")
    parser.add_argument("--analysis-stage")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.phase_epoch < 1:
        raise SystemExit("phase epoch must be positive")
    if args.phase == "ANALYZE" and (
        args.source_collection_epoch is None
        or not args.collection_cutoff_at_utc
        or not args.dataset_selection_id
    ):
        raise SystemExit("ANALYZE migration requires source epoch, cutoff and selection id")

    manifest_dir = Path(args.manifest_dir)
    history_dir = Path(args.history_dir)
    changed = 0
    preserved = 0

    for path in sorted(manifest_dir.glob("*.json")):
        raw_text = path.read_text(encoding="utf-8")
        row = json.loads(raw_text)
        if not isinstance(row, dict):
            raise SystemExit(f"{path}: manifest must be an object")

        schema = row.get("schema_version")
        if schema == "alina.resumable_campaign.v2":
            continue
        if schema != "alina.resumable_campaign.v1":
            raise SystemExit(f"{path}: unsupported schema {schema!r}")

        if (
            row.get("real_execution") is not False
            or row.get("paper_only") is not True
            or row.get("read_only") is not True
        ):
            raise SystemExit(f"{path}: unsafe manifest cannot migrate")

        # Never migrate a lineage while an old worker still owns it.
        if row.get("lease") is not None:
            raise SystemExit(f"{path}: leased V1 manifest cannot migrate")

        digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        history_target = history_dir / f"{path.stem}.v1.{digest}.json"

        migrated = {
            **row,
            "schema_version": "alina.resumable_campaign.v2",
            "migrated_from_schema_version": schema,
            "migrated_from_v1_sha256": digest,
            "migrated_from_v1_history_path": history_target.as_posix(),
            "creation_phase": args.phase,
            "phase_epoch": args.phase_epoch,
            "source_collection_epoch": args.source_collection_epoch,
            "collection_cutoff_at_utc": args.collection_cutoff_at_utc,
            "dataset_selection_id": args.dataset_selection_id,
            "analysis_stage": args.analysis_stage
            or (
                {
                    "replay": "REPLAY",
                    "backtest": "BACKTEST",
                    "oos": "OOS",
                    "forward_paper": "FORWARD_PAPER",
                    "module_pnl_proof": "PNL_PROOF",
                    "scoreboard": "SCOREBOARD",
                }.get(str(row.get("kind") or ""))
                if args.phase == "ANALYZE"
                else None
            ),
            "checkpoint_lineage": list(row.get("checkpoint_lineage") or []),
            "terminal_evidence_digest": row.get("terminal_evidence_digest")
            or (
                next(
                    iter(reversed(list((row.get("completed_units") or {}).values()))),
                    {},
                ).get("sha256")
                if row.get("status") == "COMPLETE"
                else hashlib.sha256(
                    json.dumps(
                        {
                            "campaign_id": row.get("campaign_id"),
                            "status": row.get("status"),
                            "reason": row.get("status_reason"),
                            "completed_units": row.get("completed_units") or {},
                            "checkpoint_lineage": row.get("checkpoint_lineage") or [],
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()
                if row.get("status") in {"COMPLETE", "FAILED", "UNAVAILABLE", "PARTIAL", "REJECT"}
                else None
            ),
        }

        if args.apply:
            preserved_path = _preserve_v1(
                history_dir=history_dir,
                source_path=path,
                raw_text=raw_text,
                digest=digest,
            )
            if preserved_path != history_target:
                raise SystemExit(f"{path}: preserved V1 path mismatch")
            _atomic_write(path, json.dumps(migrated, sort_keys=True, indent=2) + "\n")
            preserved += 1

        changed += 1

    print(
        json.dumps(
            {
                "migrated": changed,
                "historical_v1_preserved": preserved,
                "applied": args.apply,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

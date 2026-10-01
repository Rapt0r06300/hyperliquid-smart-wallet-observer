#!/usr/bin/env python3
"""Fail-closed validation of durable publication receipts."""
from __future__ import annotations

import json
import re
from pathlib import Path


def main():
    root = Path("catalog/receipts")
    if not root.is_dir():
        return
    seen = set()
    for path in sorted(root.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "schema", "receipt_id", "campaign_id", "unit_id", "kind",
            "status", "phase", "phase_epoch", "code_sha",
            "dataset_generation", "result_sha256", "payload_digest",
        }
        missing = required - set(row)
        if missing:
            raise SystemExit(f"{path}: missing {sorted(missing)}")
        if row["schema"] not in {"alina.publication_receipt.v1", "alina.publication_receipt.v2"}:
            raise SystemExit(f"{path}: unsupported schema")
        if row["schema"] == "alina.publication_receipt.v2":
            for key in ("alina_head", "dataset_head", "manifest_sha256", "publication_state"):
                if row.get(key) in (None, ""):
                    raise SystemExit(f"{path}: missing cross-repository publication field {key}")
            if len(str(row["manifest_sha256"])) != 64:
                raise SystemExit(f"{path}: invalid manifest_sha256")
        expected_id=f'{row["campaign_id"]}:u{row["unit_id"]}'
        if row["receipt_id"] != expected_id:
            raise SystemExit(f"{path}: receipt identity mismatch")
        if path.stem != f'{row["campaign_id"]}-u{row["unit_id"]}':
            raise SystemExit(f"{path}: receipt filename identity mismatch")
        if row["receipt_id"] in seen:
            raise SystemExit(f"{path}: duplicate receipt identity")
        seen.add(row["receipt_id"])
        if row["paper_only"] is not True or row["read_only"] is not True or row["real_execution"] is not False:
            raise SystemExit(f"{path}: unsafe receipt flags")
        if not isinstance(row["phase_epoch"], int) or row["phase_epoch"] < 1:
            raise SystemExit(f"{path}: invalid phase epoch")
        if row["phase"] not in {"COLLECT", "ANALYZE"}:
            raise SystemExit(f"{path}: invalid phase")
        if not re.fullmatch(r"[0-9a-f]{40}", str(row["code_sha"])):
            raise SystemExit(f"{path}: invalid code sha")
        if row["phase"] == "ANALYZE":
            for key in (
                "source_collection_epoch",
                "collection_cutoff_at_utc",
                "dataset_selection_id",
                "analysis_stage",
            ):
                if row.get(key) in (None, ""):
                    raise SystemExit(f"{path}: missing frozen lineage field {key}")
        if (
            row["kind"] == "market_collection"
            and row.get("universe_discovery_required") is True
            and len(str(row.get("collection_plan_sha256") or "")) != 64
        ):
            raise SystemExit(f"{path}: missing discovered-universe digest")
        for key in ("result_sha256", "payload_digest"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(row[key])):
                raise SystemExit(f"{path}: invalid {key}")
    print(f"validated {len(seen)} publication receipts")


if __name__ == "__main__":
    main()

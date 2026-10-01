#!/usr/bin/env python3
"""Validate durable phase and analysis-stage receipts."""
from __future__ import annotations

import json
import re
from pathlib import Path


def main():
    root = Path("control/phase-receipts")
    seen = set()
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        key = (row.get("schema"), row.get("request_id"))
        if key in seen:
            raise SystemExit(f"{path}: duplicate receipt identity")
        seen.add(key)
        if row.get("paper_only") is not True or row.get("read_only") is not True or row.get("real_execution") is not False:
            raise SystemExit(f"{path}: unsafe receipt flags")
        if row.get("schema") not in {"alina.phase_transition_receipt.v1", "alina.analysis_stage_receipt.v1"}:
            raise SystemExit(f"{path}: unsupported receipt schema")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("request_id") or "")):
            raise SystemExit(f"{path}: invalid request id")
        if not isinstance(row.get("new_epoch", row.get("epoch")), int) or int(row.get("new_epoch", row.get("epoch"))) < 1:
            raise SystemExit(f"{path}: invalid epoch")
        if not isinstance(row.get("epoch"), int) and row.get("schema") == "alina.analysis_stage_receipt.v1":
            raise SystemExit(f"{path}: invalid analysis epoch")
        digest = str(row.get("state_digest") or "")
        if len(digest) != 64:
            raise SystemExit(f"{path}: invalid state digest")
    print(f"validated {len(seen)} phase receipts")


if __name__ == "__main__":
    main()

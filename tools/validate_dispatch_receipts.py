#!/usr/bin/env python3
"""Validate cross-repository dispatch receipts against campaign manifests."""
from __future__ import annotations

import json
import re
from pathlib import Path

COLLECT_KINDS = {
    "market_collection", "copy_vault_collection",
    "official_archive_collection", "event_intelligence_collection",
}
ANALYZE_KINDS = {
    "replay", "backtest", "oos", "forward_paper",
    "module_pnl_proof", "scoreboard",
}


def main():
    root = Path("catalog/dispatch-receipts")
    if not root.is_dir():
        return
    seen = set()
    for path in sorted(root.glob("*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "schema", "request_id", "campaign_id", "main_code_sha",
            "dataset_repo_sha", "creation_phase", "phase_epoch",
        }
        missing = required - set(receipt)
        if missing:
            raise SystemExit(f"{path}: missing {sorted(missing)}")
        if receipt["schema"] != "alina.dispatch_receipt.v1":
            raise SystemExit(f"{path}: unsupported schema")
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt["request_id"])):
            raise SystemExit(f"{path}: invalid request id")
        if not re.fullmatch(r"[0-9a-f]{40}", str(receipt["main_code_sha"])):
            raise SystemExit(f"{path}: invalid main code sha")
        if not re.fullmatch(r"[0-9a-f]{40}", str(receipt["dataset_repo_sha"])):
            raise SystemExit(f"{path}: invalid dataset sha")
        if str(receipt["campaign_id"]) != str(receipt["campaign_id"]).strip():
            raise SystemExit(f"{path}: campaign id is not canonical")
        if (
            receipt["paper_only"] is not True
            or receipt["read_only"] is not True
            or receipt["real_execution"] is not False
        ):
            raise SystemExit(f"{path}: unsafe receipt")
        if receipt["creation_phase"] not in {"COLLECT", "ANALYZE"}:
            raise SystemExit(f"{path}: invalid phase identity")
        if receipt.get("strategy_family", "all") not in {"all", "copy_vault", "lead_lag", "cross_venue_dislocation"}:
            raise SystemExit(f"{path}: invalid strategy family")
        if not isinstance(receipt["phase_epoch"], int) or receipt["phase_epoch"] < 1:
            raise SystemExit(f"{path}: invalid phase epoch")
        key = (receipt["request_id"], receipt["campaign_id"])
        if key in seen:
            raise SystemExit(f"{path}: duplicate dispatch identity")
        seen.add(key)
        ack_path = Path("catalog/operator-acks") / (str(receipt["campaign_id"]) + ".json")
        if ack_path.is_file():
            ack = json.loads(ack_path.read_text(encoding="utf-8"))
            if ack.get("schema") != "alina.operator_ack.v1" or ack.get("state") != "MATERIALIZED":
                raise SystemExit(f"{path}: invalid operator acknowledgement")
            for field in ("request_id", "campaign_id", "main_code_sha", "dataset_repo_sha", "phase", "phase_epoch"):
                if ack.get(field) != receipt.get(field if field != "phase" else "creation_phase"):
                    raise SystemExit(f"{path}: operator acknowledgement mismatch: {field}")
        campaign_path = Path("catalog/campaigns") / (str(receipt["campaign_id"]) + ".json")
        if not campaign_path.is_file():
            raise SystemExit(f"{path}: missing campaign manifest")
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        if str(receipt["campaign_id"]).startswith("operator-") and campaign.get("operator_request_id") != receipt["request_id"]:
            raise SystemExit(f"{path}: operator request identity mismatch")
        for field in ("code_sha", "creation_phase", "phase_epoch"):
            expected = receipt["main_code_sha"] if field == "code_sha" else receipt[field]
            if campaign.get(field) != expected:
                raise SystemExit(f"{path}: campaign {field} mismatch")
        kind = str(campaign.get("kind") or "")
        allowed = COLLECT_KINDS if receipt["creation_phase"] == "COLLECT" else ANALYZE_KINDS
        if kind not in allowed:
            raise SystemExit(f"{path}: campaign kind {kind!r} is invalid for phase")
        if receipt["creation_phase"] == "ANALYZE":
            for field in ("source_collection_epoch", "collection_cutoff_at_utc", "dataset_selection_id"):
                if campaign.get(field) in (None, ""):
                    raise SystemExit(f"{path}: analysis campaign missing {field}")
            if receipt.get("source_collection_epoch") not in (None, campaign["source_collection_epoch"]):
                raise SystemExit(f"{path}: source epoch mismatch")
    print(f"validated {len(seen)} dispatch receipts")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Reconcile publication receipts with durable campaign manifests fail-closed."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def reconcile(
    receipt_dir: Path,
    campaign_dir: Path,
    *,
    phase_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    checked = 0
    receipts: dict[tuple[str, str], dict[str, Any]] = {}

    for receipt_path in sorted(receipt_dir.glob("*.json")):
        row = _load(receipt_path)
        if not isinstance(row, dict):
            errors.append({"receipt": str(receipt_path), "code": "RECEIPT_INVALID_JSON"})
            continue
        if row.get("schema") != "alina.publication_receipt.v2":
            continue
        checked += 1
        campaign_id = str(row.get("campaign_id") or "").strip()
        unit_id = str(row.get("unit_id") or "").strip()
        if not campaign_id or not unit_id:
            errors.append({"receipt": str(receipt_path), "code": "RECEIPT_IDENTITY_MISSING"})
            continue
        identity = (campaign_id, unit_id)
        if identity in receipts:
            errors.append({
                "receipt": str(receipt_path),
                "code": "DUPLICATE_PUBLICATION_RECEIPT_IDENTITY",
                "campaign_id": campaign_id,
                "unit_id": unit_id,
            })
            continue
        receipts[identity] = row

        for key in ("alina_head", "dataset_head"):
            value = str(row.get(key) or "").lower()
            if value and not re.fullmatch(r"[0-9a-f]{40}", value):
                errors.append({"receipt": str(receipt_path), "code": f"INVALID_{key.upper()}"})

        manifest_path = campaign_dir / f"{campaign_id}.json"
        if not manifest_path.is_file():
            errors.append({"receipt": str(receipt_path), "code": "CAMPAIGN_MANIFEST_MISSING"})
            continue
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        if row.get("manifest_sha256") != manifest_sha:
            errors.append({"receipt": str(receipt_path), "code": "MANIFEST_SHA256_MISMATCH"})
        manifest = _load(manifest_path)
        if not isinstance(manifest, dict):
            errors.append({"receipt": str(receipt_path), "code": "CAMPAIGN_MANIFEST_INVALID"})
            continue
        units = manifest.get("completed_units") or {}
        if unit_id not in units:
            errors.append({
                "receipt": str(receipt_path),
                "code": "PUBLISHED_UNIT_NOT_IN_MANIFEST",
                "unit_id": unit_id,
            })
        elif (
            row.get("checkpoint_id")
            and isinstance(units.get(unit_id), dict)
            and units[unit_id].get("sha256") != row.get("checkpoint_id")
        ):
            errors.append({
                "receipt": str(receipt_path),
                "code": "CHECKPOINT_DIGEST_MISMATCH",
                "unit_id": unit_id,
            })
        if manifest.get("code_sha") not in (None, row.get("alina_head")):
            errors.append({"receipt": str(receipt_path), "code": "ALINA_CODE_SHA_MISMATCH"})
        if row.get("publication_state") not in {
            "RELEASE_AND_RECEIPT_WRITTEN",
            "RECONCILED",
        }:
            errors.append({
                "receipt": str(receipt_path),
                "code": "PUBLICATION_STATE_NOT_RECONCILABLE",
            })

    current_epoch = None
    if phase_path is not None:
        phase = _load(phase_path)
        if isinstance(phase, dict):
            try:
                current_epoch = int(phase.get("epoch"))
            except (TypeError, ValueError):
                current_epoch = None

    # Reverse reconciliation closes the failure window where the durable asset
    # and terminal checkpoint exist but a publication receipt was never pushed.
    # Scope this to the active phase epoch so historical pre-receipt campaigns
    # remain auditable without being retroactively rewritten.
    missing_receipts = 0
    if current_epoch is not None:
        for manifest_path in sorted(campaign_dir.glob("*.json")):
            manifest = _load(manifest_path)
            if not isinstance(manifest, dict):
                continue
            if manifest.get("schema_version") != "alina.resumable_campaign.v2":
                continue
            if manifest.get("phase_epoch") != current_epoch:
                continue
            campaign_id = str(manifest.get("campaign_id") or manifest_path.stem)
            units = manifest.get("completed_units")
            if not isinstance(units, dict):
                continue
            for unit_id, unit in sorted(units.items(), key=lambda item: str(item[0])):
                result = unit.get("result") if isinstance(unit, dict) else None
                if not isinstance(result, dict) or result.get("durable_persisted") is not True:
                    continue
                identity = (campaign_id, str(unit_id))
                if identity not in receipts:
                    missing_receipts += 1
                    errors.append({
                        "campaign": str(manifest_path),
                        "campaign_id": campaign_id,
                        "unit_id": str(unit_id),
                        "code": "DURABLE_UNIT_RECEIPT_MISSING",
                    })

    reconciliation_digest = hashlib.sha256(
        json.dumps(
            {"checked": checked, "missing_receipts": missing_receipts, "errors": errors},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "checked": checked,
        "missing_receipts": missing_receipts,
        "errors": errors,
        "error_count": len(errors),
        "reconciliation_digest": reconciliation_digest,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--receipt-dir", default="catalog/receipts")
    p.add_argument("--campaign-dir", default="catalog/campaigns")
    p.add_argument("--phase-path", default="control/alina-phase.json")
    a = p.parse_args()
    report = reconcile(
        Path(a.receipt_dir),
        Path(a.campaign_dir),
        phase_path=Path(a.phase_path) if a.phase_path else None,
    )
    print(
        json.dumps(
            {
                "checked": report["checked"],
                "missing_receipts": report["missing_receipts"],
                "errors": report["error_count"],
                "reconciliation_digest": report["reconciliation_digest"],
            },
            sort_keys=True,
        )
    )
    if report["error_count"]:
        raise SystemExit("publication consistency reconciliation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

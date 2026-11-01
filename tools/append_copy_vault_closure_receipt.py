#!/usr/bin/env python3
"""Append exact-HEAD Copy-Vault receipts to a closure wrapper.

This small utility is deliberately append-only.  It never replaces an existing
receipt, rewrites SAFE data, or upgrades an evidence decision.  It accepts a
single receipt object or a one-level JSON list (as emitted by the restoration
evidence builder) and rejects malformed or SHA-unbound input before touching
the wrapper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path}") from exc


def _receipt_digest(receipt: dict[str, Any]) -> str:
    value = receipt.get("receipt_sha256")
    if isinstance(value, str) and value:
        return value
    canonical = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _normalise_receipts(value: Any) -> list[dict[str, Any]]:
    values = value if isinstance(value, list) else [value]
    if not values or not all(isinstance(item, dict) for item in values):
        raise ValueError("receipt input must be an object or a non-empty list of objects")
    receipts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        head_sha = item.get("head_sha")
        status = item.get("evidence_status")
        decision = item.get("decision")
        if not isinstance(head_sha, str) or not _SHA_RE.fullmatch(head_sha):
            raise ValueError("every receipt must contain a lowercase 40-character head_sha")
        if not isinstance(status, str) or not status:
            raise ValueError("every receipt must contain evidence_status")
        if not isinstance(decision, str) or not decision:
            raise ValueError("every receipt must contain decision")
        digest = _receipt_digest(item)
        if digest in seen:
            continue
        seen.add(digest)
        receipts.append(item)
    return receipts


def append_receipts(wrapper_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Append new receipt objects without replacing existing wrapper entries."""
    wrapper_value = _load_json(wrapper_path) if wrapper_path.exists() else []
    if not isinstance(wrapper_value, list) or not all(
        isinstance(item, dict) for item in wrapper_value
    ):
        raise ValueError("closure wrapper must be a JSON list of receipt objects")
    incoming = _normalise_receipts(_load_json(receipt_path))
    existing_digests = {_receipt_digest(item) for item in wrapper_value}
    added: list[dict[str, Any]] = []
    for receipt in incoming:
        digest = _receipt_digest(receipt)
        if digest not in existing_digests:
            wrapper_value.append(receipt)
            existing_digests.add(digest)
            added.append(receipt)
    if added:
        wrapper_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper_path.write_text(
            json.dumps(wrapper_value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return {
        "wrapper": str(wrapper_path),
        "incoming": len(incoming),
        "added": len(added),
        "total": len(wrapper_value),
        "append_only": True,
        "added_receipt_sha256": [_receipt_digest(item) for item in added],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrapper", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = append_receipts(args.wrapper, args.receipt)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

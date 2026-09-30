#!/usr/bin/env python3
"""Fail closed when the generated six-venue capability registry is malformed."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

VENUES = {"hyperliquid", "binance", "bybit", "okx", "gate", "bitget"}
CAPABILITIES = {"trades", "bbo", "l2", "clock_sync", "recovery", "replay_adapter", "sequence_integrity", "venue_status", "official_archive"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", default="docs/source-capability-matrix.json")
    args = parser.parse_args()
    matrix = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
    if matrix.get("schema_version") not in {"alina.source_capability_matrix.v2", "alina.source_capability_matrix.v3", "alina.source_capability_matrix.v4"}:
        raise SystemExit("unsupported source capability matrix schema")
    digest = matrix.get("matrix_digest")
    body = dict(matrix)
    body.pop("matrix_digest", None)
    expected = hashlib.sha256(canonical(body).encode()).hexdigest()
    if digest != expected:
        raise SystemExit("source capability matrix digest mismatch")
    rules = matrix.get("source_rules")
    if not isinstance(rules, dict) or len(str(rules.get("sha256") or "")) != 64:
        raise SystemExit("source rules provenance missing")
    runtime_evidence = matrix.get("runtime_evidence")
    if matrix.get("schema_version") == "alina.source_capability_matrix.v4":
        if not isinstance(runtime_evidence, dict):
            raise SystemExit("runtime source evidence missing")
        if len(str(runtime_evidence.get("receipt_digest") or "")) != 64:
            raise SystemExit("runtime source evidence digest missing")
        if runtime_evidence.get("runner_kind") != "github-hosted":
            raise SystemExit("source capability runtime evidence is not GitHub-hosted")
        if runtime_evidence.get("paper_read_only") is not True or runtime_evidence.get("real_execution") is not False:
            raise SystemExit("source capability runtime safety invariant violated")
    rows = matrix.get("venues")
    if not isinstance(rows, list) or {row.get("venue") for row in rows} != VENUES:
        raise SystemExit("source capability matrix must contain exactly six canonical venues")
    for row in rows:
        if row.get("status") == "MISSING":
            raise SystemExit(f"venue has no structural evidence: {row.get('venue')}")
        if not isinstance(row.get("native_entrypoints"), list):
            raise SystemExit(f"native entrypoint evidence missing: {row.get('venue')}")
        if row.get("runtime_status") not in {"UNVALIDATED", "DEGRADED", "HEALTHY"}:
            raise SystemExit(f"invalid runtime status: {row.get('venue')}")
        if matrix.get("schema_version") == "alina.source_capability_matrix.v4" and row.get("runtime_status") == "UNVALIDATED":
            raise SystemExit(f"runtime status remains unvalidated: {row.get('venue')}")
        if row.get("registry", {}).get("wired") is not True:
            raise SystemExit(f"venue is not wired in canonical registry: {row.get('venue')}")
        caps = row.get("capabilities")
        if not isinstance(caps, dict) or set(caps) != CAPABILITIES:
            raise SystemExit(f"capability columns incomplete: {row.get('venue')}")
        for name, value in caps.items():
            if not isinstance(value, dict) or value.get("status") not in {"FILE_PRESENT", "MISSING"} or value.get("runtime_status") not in {"UNVALIDATED", "DEGRADED", "HEALTHY"}:
                raise SystemExit(f"invalid capability status: {row.get('venue')}:{name}")
            if matrix.get("schema_version") == "alina.source_capability_matrix.v4" and value.get("runtime_status") == "UNVALIDATED":
                raise SystemExit(f"capability remains unvalidated: {row.get('venue')}:{name}")
    print(json.dumps({"venues": len(rows), "matrix_digest": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

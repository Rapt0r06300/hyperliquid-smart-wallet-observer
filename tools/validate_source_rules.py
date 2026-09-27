#!/usr/bin/env python3
"""Validate versioned source-rule provenance and safety invariants."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required to validate source rules") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="config/source_rules.yaml")
    args = parser.parse_args()
    body = yaml.safe_load(Path(args.path).read_text(encoding="utf-8"))
    if not isinstance(body, dict) or body.get("schema_version") != "alina.source_rules.v1":
        raise SystemExit("unsupported source rules schema")
    rules = body.get("rules")
    if not isinstance(rules, dict):
        raise SystemExit("source rules must contain rules")
    hl = rules.get("hyperliquid") or {}
    if hl.get("info_time_range_max_items") != 500:
        raise SystemExit("Hyperliquid pagination bound must be 500")
    if hl.get("pagination_cursor") != "last_returned_timestamp":
        raise SystemExit("Hyperliquid pagination cursor rule missing")
    if hl.get("user_websocket_snapshot_field") != "isSnapshot":
        raise SystemExit("Hyperliquid snapshot rule missing")
    if hl.get("execution_endpoint_operational") is not False:
        raise SystemExit("Hyperliquid execution endpoint must remain disabled")
    actions = rules.get("github_actions") or {}
    if actions.get("hosted_job_max_seconds") != 21600:
        raise SystemExit("GitHub-hosted six-hour bound missing")
    execution = rules.get("execution") or {}
    if execution != {
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "exchange_endpoint_operational": False,
    }:
        raise SystemExit("unsafe or incomplete execution policy")
    print(json.dumps({"schema_version": body["schema_version"], "rules": len(rules)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

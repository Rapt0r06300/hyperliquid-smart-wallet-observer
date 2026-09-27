#!/usr/bin/env python3
"""Validate versioned source-rule provenance and safety invariants."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

def _scalar(value: str) -> object:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    try:
        return int(value)
    except ValueError:
        return value.strip("'\\\"")


def _load_rules(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        # The checked-in rules file is intentionally a scalar-only YAML document.
        # Keep the validator usable on a clean GitHub-hosted Python image.
        root: dict[str, object] = {}
        stack: list[tuple[int, dict]] = [(-1, root)]
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            key, sep, value = line.strip().partition(":")
            if not sep:
                continue
            while stack and indent <= stack[-1][0]:
                stack.pop()
            parent = stack[-1][1]
            if value.strip():
                parent[key] = _scalar(value)
            else:
                child: dict[str, object] = {}
                parent[key] = child
                stack.append((indent, child))
        return root
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="config/source_rules.yaml")
    args = parser.parse_args()
    body = _load_rules(Path(args.path))
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
    if actions.get("successor_dispatch") != "workflow_dispatch_or_repository_dispatch":
        raise SystemExit("successor dispatch must use explicit workflow dispatch")
    if actions.get("token_push_recursion_assumed") is not False:
        raise SystemExit("GITHUB_TOKEN push recursion must not be assumed")
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

#!/usr/bin/env python3
"""Generate a conservative, machine-readable source-capability matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

VENUES = ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget")
CAPABILITIES = ("trades", "bbo", "l2", "clock_sync", "recovery", "replay_adapter", "sequence_integrity", "venue_status", "official_archive")
NATIVE_MODULES = {
    "hyperliquid": ("src/hl_observer/venues/hyperliquid.py", "src/hl_observer/collection/hyperliquid_clock_sync.py"),
    "binance": ("src/hl_observer/venues/binance.py",),
    "bybit": ("src/hl_observer/venues/bybit.py",),
    "okx": ("src/hl_observer/venues/okx.py",),
    "gate": ("src/hl_observer/venues/gate.py",),
    "bitget": ("src/hl_observer/venues/bitget.py",),
}
KEYWORDS = {
    "trades": ("trade", "fills"),
    "bbo": ("bbo", "best_bid", "best_ask"),
    "l2": ("l2", "orderbook", "depth"),
    "clock_sync": ("clock", "offset", "rtt"),
    "recovery": ("reconnect", "backfill", "resume"),
    "replay_adapter": ("replay", "normaliz"),
    "sequence_integrity": ("sequence", "prev_seq", "gap"),
    "venue_status": ("status", "maintenance", "trading_state"),
    "official_archive": ("archive", "historical", "download"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="src/hl_observer")
    parser.add_argument("--output", default="docs/source-capability-matrix.json")
    parser.add_argument("--runtime-evidence", default="docs/source-capability-runtime.json")
    args = parser.parse_args()

    runtime = {}
    runtime_path = Path(args.runtime_evidence)
    if runtime_path.is_file():
        try:
            candidate = json.loads(runtime_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            candidate = {}
        supplied = candidate.get("receipt_digest") if isinstance(candidate, dict) else None
        body = dict(candidate) if isinstance(candidate, dict) else {}
        body.pop("receipt_digest", None)
        expected = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest() if body else None
        if (
            candidate.get("schema_version") == "alina.source_capability_runtime.v1"
            and supplied == expected
            and candidate.get("runner_kind") == "github-hosted"
            and candidate.get("paper_read_only") is True
            and candidate.get("real_execution") is False
        ):
            runtime = candidate

    root = Path(args.root)
    files = [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".yml", ".yaml", ".json"}
    ]
    registry_path = root / "venues" / "registre_venues.py"
    registry_text = (
        registry_path.read_text(encoding="utf-8", errors="ignore").lower()
        if registry_path.exists() else ""
    )
    runtime_venues = runtime.get("venues") if isinstance(runtime.get("venues"), dict) else {}
    rows = []
    for venue in VENUES:
        runtime_row = runtime_venues.get(venue) if isinstance(runtime_venues.get(venue), dict) else {}
        venue_runtime = str(runtime_row.get("runtime_status") or "UNVALIDATED")
        if venue_runtime not in {"UNVALIDATED", "DEGRADED", "HEALTHY"}:
            venue_runtime = "UNVALIDATED"
        capability_runtime = runtime_row.get("capability_runtime") if isinstance(runtime_row.get("capability_runtime"), dict) else {}
        tokens = (venue, venue.replace("_", "-"))
        evidence = sorted({
            str(path) for path in files
            if any(
                token in path.name.lower()
                or token in path.read_text(encoding="utf-8", errors="ignore")[:200_000].lower()
                for token in tokens
            )
        })[:100]
        caps = {}
        for capability, keywords in KEYWORDS.items():
            hits = [
                path for path in evidence
                if any(
                    keyword in Path(path).read_text(
                        encoding="utf-8", errors="ignore"
                    ).lower()
                    for keyword in keywords
                )
            ]
            caps[capability] = {
                "status": "FILE_PRESENT" if hits else "MISSING",
                "runtime_status": (
                    str(capability_runtime.get(capability) or venue_runtime)
                    if hits else "DEGRADED"
                ),
                "runtime_reason": runtime_row.get("reason"),
                "evidence": sorted(hits)[:20],
            }
        module_token = f"{venue},"
        registry_wired = (
            venue in registry_text
            and module_token in registry_text
            and f"{venue}," in registry_text
        )
        rows.append({
            "venue": venue,
            "status": "FILE_PRESENT" if evidence else "MISSING",
            "runtime_status": venue_runtime,
            "runtime_reason": runtime_row.get("reason"),
            "runtime_observed_at_utc": runtime_row.get("observed_at_utc"),
            "evidence_files": evidence,
            "native_entrypoints": [
                module for module in NATIVE_MODULES.get(venue, ())
                if (root.parent.parent / module).exists()
            ],
            "required_strategy_families": [
                "copy_vault", "lead_lag", "cross_venue_dislocation"
            ],
            "registry": {
                "path": str(registry_path),
                "wired": registry_wired,
                "policy": "registry wiring is structural evidence only",
            },
            "capabilities": caps,
        })
    rules_path = root.parent.parent / "config" / "source_rules.yaml"
    body = {
        "schema_version": "alina.source_capability_matrix.v4",
        "runtime_evidence": {
            "path": str(runtime_path),
            "receipt_digest": runtime.get("receipt_digest"),
            "github_sha": runtime.get("github_sha"),
            "github_run_id": runtime.get("github_run_id"),
            "runner_kind": runtime.get("runner_kind"),
            "paper_read_only": runtime.get("paper_read_only"),
            "real_execution": runtime.get("real_execution"),
        },
        "source_rules": {
            "path": str(rules_path),
            "sha256": hashlib.sha256(rules_path.read_bytes()).hexdigest() if rules_path.is_file() else None,
        },
        "source_root": args.root,
        "venues": rows,
        "policy": (
            "FILE_PRESENT and registry.wired are not IMPORT_OK, "
            "COLLECTOR_ACTIVE, SOURCE_HEALTHY, REPLAY_COMPATIBLE or PNL_READY"
        ),
    }
    body["matrix_digest"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    Path(args.output).write_text(
        json.dumps(body, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": args.output,
        "venues": len(rows),
        "matrix_digest": body["matrix_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

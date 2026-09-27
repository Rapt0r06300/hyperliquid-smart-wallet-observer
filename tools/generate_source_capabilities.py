#!/usr/bin/env python3
"""Generate a conservative, machine-readable source-capability matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

VENUES = ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget")
CAPABILITIES = ("trades", "bbo", "l2", "clock_sync", "recovery", "replay_adapter")
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
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="src/hl_observer")
    parser.add_argument("--output", default="docs/source-capability-matrix.json")
    args = parser.parse_args()

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
    rows = []
    for venue in VENUES:
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
                "runtime_status": "UNVALIDATED",
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
            "runtime_status": "UNVALIDATED",
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
    body = {
        "schema_version": "alina.source_capability_matrix.v3",
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

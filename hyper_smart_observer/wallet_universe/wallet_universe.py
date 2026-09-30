from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(slots=True)
class WalletUniverseEntry:
    wallet_address: str
    sources: set[str] = field(default_factory=set)
    first_seen_ms: int | None = None
    last_seen_ms: int | None = None
    last_scanned_ms: int | None = None
    scan_priority: float = 0.0
    quality_score: float = 0.0
    copyability_score: float = 0.0
    consensus_score: float = 0.0
    recent_actions: list[str] = field(default_factory=list)
    active_position_summary: str = ""
    pnl_summary: str = ""
    simulation_result_summary: str = ""
    risk_flags: list[str] = field(default_factory=list)
    status: str = "DISCOVERED"


@dataclass(slots=True)
class WalletUniverseImportResult:
    imported: int
    rejected: int
    duplicates: int
    entries: list[WalletUniverseEntry]
    rejected_reasons: list[str]


def import_wallet_universe_lines(lines: list[str], *, source: str = "manual_import") -> WalletUniverseImportResult:
    entries: dict[str, WalletUniverseEntry] = {}
    rejected_reasons: list[str] = []
    duplicates = 0
    for raw in lines:
        wallet = str(raw or "").strip().split(",")[0].strip()
        if not wallet:
            continue
        if "..." in wallet:
            rejected_reasons.append("TRUNCATED_ADDRESS_REJECTED")
            continue
        if not WALLET_RE.fullmatch(wallet):
            rejected_reasons.append("INVALID_ADDRESS_REJECTED")
            continue
        key = wallet.lower()
        if key in entries:
            duplicates += 1
            entries[key].sources.add(source)
            continue
        entries[key] = WalletUniverseEntry(
            wallet_address=key,
            sources={source},
            scan_priority=10.0,
            quality_score=0.0,
            copyability_score=0.0,
            status="IMPORTED" if source != "local_fixture" else "DISCOVERED",
        )
    return WalletUniverseImportResult(
        imported=len(entries),
        rejected=len(rejected_reasons),
        duplicates=duplicates,
        entries=list(entries.values()),
        rejected_reasons=rejected_reasons,
    )


def import_wallet_universe_file(path: Path, *, source: str = "manual_import") -> WalletUniverseImportResult:
    return import_wallet_universe_lines(path.read_text(encoding="utf-8").splitlines(), source=source)

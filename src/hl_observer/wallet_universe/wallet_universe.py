from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(slots=True)
class WalletUniverseEntry:
    wallet_address: str
    sources: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)
    status: str = "DISCOVERED"


@dataclass(slots=True)
class WalletUniverseImportResult:
    imported: int
    rejected: int
    duplicates: int
    entries: list[WalletUniverseEntry]
    rejected_reasons: list[str]


@dataclass(frozen=True, slots=True)
class WalletIdentityReceipt:
    wallet_address: str
    native_identity: str | None
    source: str | None
    proof_sha256: str | None
    status: str
    reason: str | None = None


def wallet_identity_receipt(
    *, wallet_address: Any, native_identity: Any, source: Any, proof_sha256: Any
) -> WalletIdentityReceipt:
    """Require explicit provenance before linking a proxy/source to a wallet."""

    address = str(wallet_address or "").strip().lower()
    native = str(native_identity or "").strip()
    source_text = str(source or "").strip()
    digest = str(proof_sha256 or "").strip().lower()
    if not WALLET_RE.fullmatch(address):
        return WalletIdentityReceipt(address, None, source_text or None, None, "UNMEASURABLE", "INVALID_WALLET")
    if not native:
        return WalletIdentityReceipt(address, None, source_text or None, None, "UNMEASURABLE", "NATIVE_IDENTITY_MISSING")
    if not source_text:
        return WalletIdentityReceipt(address, native, None, None, "UNMEASURABLE", "SOURCE_MISSING")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return WalletIdentityReceipt(address, native, source_text, None, "UNMEASURABLE", "PROOF_HASH_MISSING_OR_INVALID")
    return WalletIdentityReceipt(address, native, source_text, digest, "PROVEN")


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
        entries[key] = WalletUniverseEntry(wallet_address=key, sources={source})
    return WalletUniverseImportResult(
        imported=len(entries),
        rejected=len(rejected_reasons),
        duplicates=duplicates,
        entries=list(entries.values()),
        rejected_reasons=rejected_reasons,
    )


def import_wallet_universe_file(path: Path, *, source: str = "manual_import") -> WalletUniverseImportResult:
    return import_wallet_universe_lines(path.read_text(encoding="utf-8").splitlines(), source=source)


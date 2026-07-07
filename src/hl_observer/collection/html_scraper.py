from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256


FULL_WALLET_RE = re.compile(r"0x[a-fA-F0-9]{40}")
TRUNCATED_WALLET_RE = re.compile(r"0x[a-fA-F0-9]{2,20}\.{3}[a-fA-F0-9]{2,20}")


@dataclass(frozen=True, slots=True)
class HtmlWalletCandidate:
    address: str
    source_url: str
    raw_hash: str
    evidence: str = "html_public_page"


@dataclass(frozen=True, slots=True)
class HtmlScrapeResult:
    source_url: str
    candidates: tuple[HtmlWalletCandidate, ...]
    truncated_rejected: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    raw_hash: str = ""
    data_fabricated: bool = False
    read_only: bool = True


def parse_wallets_from_html(html: str, *, source_url: str) -> HtmlScrapeResult:
    text = str(html or "")
    raw_hash = sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    truncated = tuple(dict.fromkeys(match.group(0) for match in TRUNCATED_WALLET_RE.finditer(text)))
    full = tuple(dict.fromkeys(match.group(0).lower() for match in FULL_WALLET_RE.finditer(text)))
    candidates = tuple(
        HtmlWalletCandidate(address=address, source_url=source_url, raw_hash=raw_hash)
        for address in full
        if not any(address.startswith(item.split("...", 1)[0].lower()) for item in truncated)
    )
    warnings: list[str] = []
    if truncated:
        warnings.append("TRUNCATED_ADDRESS_REJECTED")
    if not candidates:
        warnings.append("NO_FULL_WALLET_FOUND")
    return HtmlScrapeResult(
        source_url=source_url,
        candidates=candidates,
        truncated_rejected=truncated,
        warnings=tuple(warnings),
        raw_hash=raw_hash,
    )

from __future__ import annotations

from hl_observer.explorer.explorer_models import ExplorerResult, ExplorerSourceStatus
from hl_observer.explorer.explorer_parser import parse_explorer_payload


def extract_explorer_dom(html: str, *, source_url: str = "dom_fixture") -> ExplorerResult:
    transactions, truncated = parse_explorer_payload(html, source_url=source_url)
    result = ExplorerResult(
        method="dom",
        status=ExplorerSourceStatus.OK if any(tx.wallet_address for tx in transactions) else ExplorerSourceStatus.IMPORT_REQUIRED,
        events_seen=len(transactions),
        transactions=transactions,
        full_addresses_found=len({tx.wallet_address for tx in transactions if tx.wallet_address}),
        truncated_addresses_rejected=truncated,
        candidates_created=len({tx.wallet_address for tx in transactions if tx.wallet_address}),
        notes=["dom_payload_parsed", "no_address_completion"],
    )
    if result.full_addresses_found == 0:
        result.notes.append("import_required_if_public_dom_only_shows_truncated_addresses")
    return result.finish()


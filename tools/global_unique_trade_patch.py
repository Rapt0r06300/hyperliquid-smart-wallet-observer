"""Read and write compact, SHA-bound global unique-trade patch rows.

Version 5 stores each shard proof as a fixed-order array to avoid repeating
field names and the identity version hundreds of thousands of times.  Version
4 and the pre-versioned mapping layout remain readable for existing catalogs.
"""
from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

SCHEMA_V4 = "alina.global_unique_trade_patch.v4"
SCHEMA_V5 = "alina.global_unique_trade_patch.v5"
GLOBAL_IDENTITY_VERSION = "native-id-or-venue-family-symbol-time-side-price-size-v3-full-string"

# v5 counts[dataset_id] = [asset_sha256, scanned, unique, global_new, overlap, exact]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class CompactGlobalUniqueCountRows(Mapping[str, Mapping[str, Any]]):
    """Lazy mapping view so v5 arrays stay compact while consumers iterate IDs."""

    def __init__(
        self,
        rows: Mapping[str, Any],
        *,
        identity_version: str,
    ) -> None:
        self._rows = rows
        self._identity_version = identity_version

    def __getitem__(self, dataset_id: str) -> Mapping[str, Any]:
        try:
            raw = self._rows[dataset_id]
        except KeyError:
            raise
        if not isinstance(raw, list) or len(raw) != 6:
            raise KeyError(dataset_id)
        asset_sha, scanned, unique, global_new, overlap, exact = raw
        if (
            not isinstance(asset_sha, str)
            or _SHA256.fullmatch(asset_sha) is None
            or any(type(value) is not int for value in (scanned, unique, global_new, overlap))
            or type(exact) is not bool
            or exact is not True
            or min(scanned, unique, global_new, overlap) < 0
            or unique > scanned
            or global_new > unique
            or overlap != unique - global_new
        ):
            # Mapping.get() will treat a malformed row as absent, so no consumer
            # can promote it as exact evidence.
            raise KeyError(dataset_id)
        return {
            "asset_sha256": asset_sha,
            "trade_count_scanned": scanned,
            "unique_trade_count": unique,
            "global_new_identity_count": global_new,
            "cross_shard_overlap_count": overlap,
            "unique_trade_count_exact": True,
            "identity_version": self._identity_version,
        }

    def __iter__(self) -> Iterator[str]:
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


def global_unique_count_rows(document: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    """Return a compatibility view of per-shard proofs; unknown schemas fail closed."""
    counts = document.get("counts")
    if not isinstance(counts, Mapping):
        return {}
    schema = document.get("schema")
    if schema == SCHEMA_V5:
        identity_version = document.get("identity_version")
        if identity_version != GLOBAL_IDENTITY_VERSION:
            return {}
        return CompactGlobalUniqueCountRows(counts, identity_version=identity_version)
    if schema not in (None, SCHEMA_V4):
        return {}
    return counts


def compact_global_unique_count_rows(
    rows: Mapping[str, Mapping[str, Any]],
    *,
    identity_version: str,
) -> dict[str, list[Any]]:
    """Validate v4-style proof rows and encode their lossless v5 representation."""
    if identity_version != GLOBAL_IDENTITY_VERSION:
        raise ValueError("global unique identity version unsupported")
    compact: dict[str, list[Any]] = {}
    for dataset_id in sorted(rows):
        row = rows[dataset_id]
        if not isinstance(dataset_id, str) or not dataset_id or not isinstance(row, Mapping):
            raise ValueError("global unique count row identity invalid")
        asset_sha = str(row.get("asset_sha256") or "").lower()
        scanned = row.get("trade_count_scanned")
        unique = row.get("unique_trade_count")
        global_new = row.get("global_new_identity_count")
        overlap = row.get("cross_shard_overlap_count")
        if (
            _SHA256.fullmatch(asset_sha) is None
            or any(type(value) is not int for value in (scanned, unique, global_new, overlap))
            or row.get("unique_trade_count_exact") is not True
            or row.get("identity_version") != identity_version
            or min(scanned, unique, global_new, overlap) < 0
            or unique > scanned
            or global_new > unique
            or overlap != unique - global_new
        ):
            raise ValueError(f"global unique count evidence invalid for {dataset_id}")
        compact[dataset_id] = [asset_sha, scanned, unique, global_new, overlap, True]
    return compact

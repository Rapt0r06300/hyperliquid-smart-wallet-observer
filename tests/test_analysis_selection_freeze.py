from __future__ import annotations

import hashlib
import json

import pytest

from tools.resolve_analysis_selection import resolve_selection


def _expected(source_epoch: int, cutoff: str, index_bytes: bytes) -> str:
    index_sha = hashlib.sha256(index_bytes).hexdigest()
    return hashlib.sha256(
        f"{source_epoch}|{cutoff}|{index_sha}".encode("utf-8")
    ).hexdigest()


def test_first_analysis_selection_is_derived_from_frozen_index(tmp_path):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    index = b'{"schema":"index","items":[1,2,3]}\n'
    (catalog / "DATA_INDEX.json").write_bytes(index)

    selection = resolve_selection(
        tmp_path,
        epoch=3,
        source_collection_epoch=2,
        collection_cutoff_at_utc="2026-09-29T10:56:59Z",
    )

    assert selection == _expected(2, "2026-09-29T10:56:59Z", index)


def test_existing_epoch_selection_wins_even_if_index_changes(tmp_path):
    catalog = tmp_path / "catalog"
    campaigns = catalog / "campaigns"
    campaigns.mkdir(parents=True)
    (catalog / "DATA_INDEX.json").write_text('{"version":2}\n', encoding="utf-8")
    frozen = "a" * 64
    row = {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": "analysis-e3-replay-v2",
        "kind": "replay",
        "creation_phase": "ANALYZE",
        "phase_epoch": 3,
        "source_collection_epoch": 2,
        "dataset_selection_id": frozen,
    }
    (campaigns / "analysis-e3-replay-v2.json").write_text(
        json.dumps(row), encoding="utf-8"
    )

    selection = resolve_selection(
        tmp_path,
        epoch=3,
        source_collection_epoch=2,
        collection_cutoff_at_utc="2026-09-29T10:56:59Z",
    )

    assert selection == frozen


def test_selection_drift_fails_closed(tmp_path):
    catalog = tmp_path / "catalog"
    campaigns = catalog / "campaigns"
    campaigns.mkdir(parents=True)
    (catalog / "DATA_INDEX.json").write_text("{}\n", encoding="utf-8")
    for suffix, selection in (("replay", "a" * 64), ("backtest", "b" * 64)):
        row = {
            "schema_version": "alina.resumable_campaign.v2",
            "campaign_id": f"analysis-e3-{suffix}",
            "kind": suffix,
            "creation_phase": "ANALYZE",
            "phase_epoch": 3,
            "source_collection_epoch": 2,
            "dataset_selection_id": selection,
        }
        (campaigns / f"{suffix}.json").write_text(json.dumps(row), encoding="utf-8")

    with pytest.raises(SystemExit, match="analysis selection drift detected"):
        resolve_selection(
            tmp_path,
            epoch=3,
            source_collection_epoch=2,
            collection_cutoff_at_utc="2026-09-29T10:56:59Z",
        )

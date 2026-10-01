from __future__ import annotations

import json
from pathlib import Path

from tools.augment_campaign_result import (
    annotate_collection,
    annotate_evidence,
    mark_durability_failure,
)


def _result(path: Path) -> None:
    path.write_text(
        json.dumps({
            "status":"COMPLETE",
            "sha256":"0"*64,
            "payload":{"status":"COMPLETE"},
            "progressed":True,
        }),
        encoding="utf-8",
    )


def test_collection_annotation_rehashes_and_persists_counts(tmp_path):
    result=tmp_path/"result.json"
    manifest=tmp_path/"RUN_MANIFEST.json"
    _result(result)
    manifest.write_text(
        json.dumps({
            "shard_count":4,
            "safe_count":2,
            "partial_count":1,
            "reject_count":1,
        }),
        encoding="utf-8",
    )
    before=json.loads(result.read_text())["sha256"]
    row=annotate_collection(
        result,
        manifest,
        tag="data-v2-campaign-test",
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
    )
    assert row["payload"]["durable_persisted"] is True
    assert row["payload"]["safe_count"] == 2
    assert row["sha256"] != before


def test_evidence_annotation_is_durable(tmp_path):
    result=tmp_path/"result.json"
    _result(result)
    row=annotate_evidence(
        result,
        tag="campaign-evidence-test",
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
    )
    assert row["payload"]["evidence_release_tag"]=="campaign-evidence-test"
    assert row["payload"]["durable_persisted"] is True


def test_durability_failure_never_keeps_complete(tmp_path):
    result=tmp_path/"result.json"
    _result(result)
    row=mark_durability_failure(result)
    assert row["status"]=="FAILED"
    assert row["progressed"] is False
    assert row["payload"]["failure_category"]=="INFRASTRUCTURE"

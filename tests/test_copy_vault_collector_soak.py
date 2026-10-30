from __future__ import annotations

import hashlib
import json

from tools.copy_vault_collector_soak import (
    _accepted_digest_add,
    _accepted_digest_finish,
    _accepted_digest_start,
    _canonical,
    execute_soak,
)


def test_incremental_accepted_digest_matches_canonical_json_list() -> None:
    rows = [
        {"event_id": "a", "sequence": 1, "coin": "BTC"},
        {"event_id": "b", "sequence": 2, "coin": "ETH"},
    ]
    digest, count = _accepted_digest_start()
    for row in rows:
        count = _accepted_digest_add(digest, count, row)

    assert count == len(rows)
    assert _accepted_digest_finish(digest) == hashlib.sha256(
        _canonical(rows)
    ).hexdigest()


def test_soak_resume_keeps_exact_counts_and_hashes(tmp_path) -> None:
    receipt = execute_soak(
        events_count=1_000,
        batch_size=37,
        queue_limit=64,
        interrupt_after=111,
        checkpoint_path=tmp_path / "checkpoint.json",
    )

    assert receipt["status"] == "PASS"
    assert receipt["same_result_after_resume"] is True
    assert receipt["continuous"]["accepted_count"] == 1_000
    assert receipt["resumed"]["accepted_count"] == 1_000
    assert receipt["continuous"]["accepted_sha256"] == receipt["resumed"][
        "accepted_sha256"
    ]
    assert json.loads((tmp_path / "checkpoint.json").read_text())[
        "accepted_count"
    ] == 1_000

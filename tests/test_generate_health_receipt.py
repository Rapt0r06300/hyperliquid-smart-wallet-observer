from __future__ import annotations

import hashlib

import pytest

from tools.generate_health_receipt import validate_replay_reasons_binding


def test_replay_reasons_requires_the_current_index_sha(tmp_path) -> None:
    index = tmp_path / "DATA_INDEX.json"
    index.write_text('{"shards": []}\n', encoding="utf-8")
    digest = hashlib.sha256(index.read_bytes()).hexdigest()

    binding = validate_replay_reasons_binding(
        {"source_index_sha256": digest},
        {"source_index_sha256": digest, "reason_counts": {}},
        index_sha256=digest,
    )

    assert binding == {"status": "VERIFIED", "source_index_sha256": digest}


def test_replay_reasons_stale_sha_is_rejected(tmp_path) -> None:
    index = tmp_path / "DATA_INDEX.json"
    index.write_text('{"shards": []}\n', encoding="utf-8")
    current = hashlib.sha256(index.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="STALE_INDEX"):
        validate_replay_reasons_binding(
            {"source_index_sha256": current},
            {"source_index_sha256": "0" * 64, "reason_counts": {}},
            index_sha256=current,
        )


def test_replay_reasons_without_binding_is_rejected() -> None:
    with pytest.raises(ValueError, match="BINDING_MISSING"):
        validate_replay_reasons_binding(
            {"source_index_sha256": "a" * 64},
            {"reason_counts": {}},
            index_sha256="a" * 64,
        )

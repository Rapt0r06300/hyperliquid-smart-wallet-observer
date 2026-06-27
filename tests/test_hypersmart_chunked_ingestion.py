from __future__ import annotations

from hyper_smart_observer.scale.chunked_ingestion import ingest_jsonl_chunks


def test_chunked_ingestion_commits_chunks_and_checkpoint(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join('{"wallet":"0x%040x","coin":"BTC"}' % i for i in range(5)), encoding="utf-8")
    chunks: list[int] = []

    result = ingest_jsonl_chunks(path, chunk_size=2, on_chunk=lambda rows: chunks.append(len(rows)))

    assert result.rows_seen == 5
    assert result.chunks_committed == 3
    assert result.checkpoint_row == 5
    assert chunks == [2, 2, 1]
    assert result.network_used is False


def test_chunked_ingestion_resume_skips_rows(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join('{"wallet":"0x%040x","coin":"BTC"}' % i for i in range(5)), encoding="utf-8")
    seen: list[int] = []

    result = ingest_jsonl_chunks(path, chunk_size=10, resume_from_row=3, on_chunk=lambda rows: seen.append(len(rows)))

    assert result.rows_seen == 5
    assert result.chunks_committed == 1
    assert seen == [2]

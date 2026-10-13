"""Read-only official Bitget trade reference probe reuses the canonical reconciler."""
from __future__ import annotations

import asyncio
import pytest

from tools import recheck_recovered_trade_reference as subject


def _index(venue="bitget",family="trades"):
    return {"release_repository_default": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "shards": [{
                "dataset_id": "candidate", "quality_status": "PARTIAL",
                "family": family, "venue": venue, "symbol": "UMAUSDT",
                "release_tag": "tag", "release_asset": "candidate.jsonl.gz",
                "sha256": "a" * 64, "bytes": 55,
            }]}


def test_bounded_reference_deficit_never_promotes(monkeypatch, tmp_path):
    def fake_inspect(*_args, **_kwargs):
        return {"status": "CONTENT_REPLAY_CHECK_PASSED_NOT_SAFE",
                "byte_coverage_verified": True,
                "manifest_reference_trades_missing_from_live": 6}
    monkeypatch.setattr(subject, "reinspect", fake_inspect)
    calls = []
    async def fake_reconcile(file, **kwargs):
        calls.append((str(file), kwargs))
        return {"status": "PARTIAL", "live_count": 53, "reference_count": 59,
                "matched_count": 53, "missing_from_live": 6}
    report = asyncio.run(subject.recheck_one(
        _index(), "b" * 64, tmp_path, "candidate",
        max_pages=3, reconciliation_function=fake_reconcile))
    assert report["status"] == "OFFICIAL_REFERENCE_INCOMPLETE_NOT_SAFE"
    assert report["original_manifest_missing_reference_trades"] == 6
    assert report["official_reference"]["missing_from_live"] == 6
    assert report["missing_trade_events_reconstructed"] == 0
    assert report["reclassified_safe"] is False
    assert report["validation_allowed"] is False
    assert calls[0][1]["max_pages"] == 3
    assert calls[0][1]["symbol"] == "UMAUSDT"


def test_matched_reference_does_not_mean_executable_replay(monkeypatch, tmp_path):
    monkeypatch.setattr(subject, "reinspect",
                        lambda *_a, **_kw: {"byte_coverage_verified": True})
    async def fake_match(*_a, **_kw):
        return {"status": "MATCHED", "reference_count": 53,
                "matched_count": 53, "missing_from_live": 0}
    report = asyncio.run(subject.recheck_one(
        _index(), "b" * 64, tmp_path, "candidate",
        reconciliation_function=fake_match))
    assert report["status"] == "OFFICIAL_REFERENCE_MATCHED_NOT_SAFE"
    assert report["replay_certified"] is False
    assert report["cross_shard_continuity_proven"] is False


def test_non_bitget_and_unverified_bytes_do_not_query_network(monkeypatch, tmp_path):
    monkeypatch.setattr(subject, "reinspect",
                        lambda *_a, **_kw: {"byte_coverage_verified": True})
    async def fail_network(*_a, **_kw):
        raise AssertionError("Should not query Bitget")
    report = asyncio.run(subject.recheck_one(
        _index("gate"), "b" * 64, tmp_path, "candidate",
        reconciliation_function=fail_network))
    assert report["status"] == "REFERENCE_NOT_APPLICABLE"
    monkeypatch.setattr(subject, "reinspect",
                        lambda *_a, **_kw: {"byte_coverage_verified": False})
    with pytest.raises(ValueError, match="SOURCE_BYTES_UNVERIFIED"):
        asyncio.run(subject.recheck_one(
            _index(), "b" * 64, tmp_path, "candidate",
            reconciliation_function=fail_network))


def test_page_budget_refuses_unbounded_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(subject, "reinspect",
                        lambda *_a, **_kw: {"byte_coverage_verified": True})
    async def fake(*_a, **_kw):
        return {"status": "UNAVAILABLE", "reason": "offline"}
    with pytest.raises(ValueError, match="INVALID_PAGE_LIMIT"):
        asyncio.run(subject.recheck_one(
            _index(), "b" * 64, tmp_path, "candidate", max_pages=100,
            reconciliation_function=fake))


def test_opt_in_bounded_rest_only_rows_are_digest_checked_without_safe_promotion(monkeypatch, tmp_path):
    import hashlib
    import json
    monkeypatch.setattr(subject, "reinspect",
                        lambda *_a, **_kw: {"byte_coverage_verified": True})
    rest_rows = [{"trade_id": "t54", "source": "BITGET_PUBLIC_REST_REFERENCE_ONLY"}]
    body = json.dumps(rest_rows, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    evidence = {
        "status": "REFERENCE_ONLY_NOT_MERGED_OR_REPLAY_CERTIFIED",
        "symbol": "UMAUSDT",
        "missing_trade_count": 1,
        "rows": rest_rows, "rows_sha256": hashlib.sha256(body).hexdigest(),
        "validation_allowed": False, "replay_certified": False,
        "reclassified_safe": False,
    }
    seen = {}
    async def fake_reconcile(_file, **kw):
        seen.update(kw)
        return {"status": "PARTIAL", "missing_from_live": 1,
                "missing_reference_evidence": evidence}
    result = asyncio.run(subject.recheck_one(
        _index(), "b" * 64, tmp_path, "candidate",
        reference_gap_export_limit=8, reconciliation_function=fake_reconcile,
    ))
    assert seen["missing_reference_rows_limit"] == 8
    assert result["official_reference"]["missing_reference_evidence"]["rows"] == rest_rows
    assert result["missing_trade_events_reconstructed"] == 0
    assert result["rest_only_missing_trades_not_merged"] is True
    assert result["validation_allowed"] is False
    assert result["reclassified_safe"] is False
    evidence["rows_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="GAP_DIGEST_MISMATCH"):
        asyncio.run(subject.recheck_one(
            _index(), "b" * 64, tmp_path, "candidate",
            reference_gap_export_limit=8, reconciliation_function=fake_reconcile,
        ))


def test_unbounded_or_unsafe_rest_only_export_is_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(subject, "reinspect",
                        lambda *_a, **_kw: {"byte_coverage_verified": True})
    async def malicious(_file, **_kw):
        return {"status": "PARTIAL", "missing_from_live": 1,
                "missing_reference_evidence": {
                    "status": "REFERENCE_GAP_EXCEEDS_BOUND_NOT_EXPORTED",
                    "rows": [{"trade_id": "injected"}]}}
    with pytest.raises(ValueError, match="INVALID_REFERENCE_EXPORT_LIMIT"):
        asyncio.run(subject.recheck_one(
            _index(), "b" * 64, tmp_path, "candidate",
            reference_gap_export_limit=129, reconciliation_function=malicious,
        ))
    with pytest.raises(ValueError, match="UNSAFE_GAP_ROWS"):
        asyncio.run(subject.recheck_one(
            _index(), "b" * 64, tmp_path, "candidate",
            reference_gap_export_limit=5, reconciliation_function=malicious,
        ))


def test_hosted_recheck_installs_declared_collection_dependencies():
    from pathlib import Path
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" /
        "catalog-partition-parity.yml"
    ).read_text(encoding="utf-8")
    assert "python -m pip install --disable-pip-version-check pytest -e ." in workflow
    assert "python -m pip install --disable-pip-version-check -e . httpx==0.28.1" in workflow
    assert "            pyproject.toml\n            README.md" in workflow


def test_recovery_hosted_manual_bitget_reference_gap_export_is_bounded():
    from pathlib import Path
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" /
        "catalog-partition-parity.yml"
    ).read_text(encoding="utf-8")
    assert "reference_gap_export_limit:" in workflow
    assert "type: number" in workflow
    assert "REFERENCE_GAP_EXPORT_LIMIT: ${{ inputs.reference_gap_export_limit || 0 }}" in workflow
    assert '--reference-gap-export-limit "$REFERENCE_GAP_EXPORT_LIMIT"' in workflow
    assert 'result.get("missing_trade_events_reconstructed", 0) == 0' in workflow

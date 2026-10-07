from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _module():
    spec = importlib.util.spec_from_file_location(
        "recover_dataset_v2_capsules_test",
        ROOT / "tools" / "recover_dataset_v2_capsules.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_recover_pending_skips_completion_receipts_without_remote_probe(
    monkeypatch,
):
    module = _module()
    releases = [
        {
            "tag_name": "alina-recovery-complete",
            "created_at": "2026-10-07T00:00:00Z",
            "assets": [{"name": module.COMPLETE_NAME}],
        },
        {
            "tag_name": "alina-recovery-pending",
            "created_at": "2026-10-07T01:00:00Z",
            "assets": [{"name": module.INDEX_NAME}],
        },
    ]
    monkeypatch.setattr(module, "list_recovery_releases", lambda _repo: releases)
    calls = []

    def fake_recover_one(_repository, release, _root):
        calls.append(release["tag_name"])
        return {
            "recovery_tag": release["tag_name"],
            "requested_tag": "data-v2-test",
            "status": "RECOVERED",
            "canonical_release_tag": "data-v2-test",
            "shard_count": 1,
        }

    monkeypatch.setattr(module, "recover_one", fake_recover_one)

    report = module.recover_pending("owner/repo", limit=1)

    assert calls == ["alina-recovery-pending"]
    assert report["already_complete"] == 1
    assert report["attempted"] == 1
    assert report["recovered"] == 1
    assert report["failures"] == []

from pathlib import Path

import hl_observer.release.release_readiness as rr
from hl_observer.release.release_readiness import check_release_readiness


def test_repo_is_release_ready():
    res = check_release_readiness(Path.cwd())
    assert res.checks["no_fake_data"] is True
    assert res.checks["safety_audit_ok"] is True
    assert res.fake_findings == 0
    assert res.ready is True and res.blockers == ()


def test_fake_findings_block_release(monkeypatch):
    monkeypatch.setattr(rr, "scan_for_fake_data", lambda *a, **k: [object(), object()])
    res = check_release_readiness(Path.cwd())
    assert res.checks["no_fake_data"] is False
    assert res.ready is False
    assert any("fake-data" in b for b in res.blockers)
    assert res.fake_findings == 2


def test_missing_doc_blocks_release(tmp_path):
    # an empty dir has none of the required docs -> not ready
    res = check_release_readiness(tmp_path)
    assert res.checks["required_docs_present"] is False
    assert res.ready is False


def test_to_dict_shape():
    res = check_release_readiness(Path.cwd())
    d = res.to_dict()
    assert set(d) == {"ready", "checks", "blockers", "fake_findings"}

"""Fail-closed sync and observer boundaries for ASF-041..056."""

from tools.sync_complete_clone import sync_clone_safety_receipt
from hl_observer.ops.global_observer_pipeline import observer_scope_safety_receipt


def _sync() -> dict[str, object]:
    return {"branch":"main","tracked_clean":True,"origin_trusted":True,"force_push":False,"reset":False,"clean":False}


def _observer() -> dict[str, object]:
    return {"strategy_family":"Copy-Vault","paper_only":True,"read_only":True,"real_execution":False,"promotion":False}


def test_asf_041_sync_positive() -> None:
    assert sync_clone_safety_receipt(_sync())["status"] == "PROVEN"


def test_asf_042_sync_requires_main() -> None:
    row = _sync(); row["branch"] = "feature"
    assert sync_clone_safety_receipt(row)["status"] == "REJECTED"


def test_asf_043_sync_requires_clean_tracked_state() -> None:
    row = _sync(); row["tracked_clean"] = False
    assert sync_clone_safety_receipt(row)["status"] == "REJECTED"


def test_asf_044_sync_requires_trusted_origin() -> None:
    row = _sync(); row["origin_trusted"] = False
    assert sync_clone_safety_receipt(row)["status"] == "REJECTED"


def test_asf_045_sync_rejects_force_push() -> None:
    row = _sync(); row["force_push"] = True
    assert sync_clone_safety_receipt(row)["status"] == "REJECTED"


def test_asf_046_sync_rejects_reset() -> None:
    row = _sync(); row["reset"] = True
    assert sync_clone_safety_receipt(row)["status"] == "REJECTED"


def test_asf_047_sync_rejects_clean() -> None:
    row = _sync(); row["clean"] = True
    assert sync_clone_safety_receipt(row)["status"] == "REJECTED"


def test_asf_048_sync_is_paper_only() -> None:
    out = sync_clone_safety_receipt(_sync())
    assert out["paper_read_only"] is True and out["real_execution"] is False


def test_asf_049_observer_positive() -> None:
    assert observer_scope_safety_receipt(_observer())["status"] == "PROVEN"


def test_asf_050_observer_requires_copy_vault() -> None:
    row = _observer(); row["strategy_family"] = "Lead-Lag"
    assert observer_scope_safety_receipt(row)["status"] == "REJECTED"


def test_asf_051_observer_requires_paper() -> None:
    row = _observer(); row["paper_only"] = False
    assert observer_scope_safety_receipt(row)["status"] == "REJECTED"


def test_asf_052_observer_requires_read_only() -> None:
    row = _observer(); row["read_only"] = False
    assert observer_scope_safety_receipt(row)["status"] == "REJECTED"


def test_asf_053_observer_rejects_execution() -> None:
    row = _observer(); row["real_execution"] = True
    assert observer_scope_safety_receipt(row)["status"] == "REJECTED"


def test_asf_054_observer_rejects_promotion() -> None:
    row = _observer(); row["promotion"] = True
    assert observer_scope_safety_receipt(row)["status"] == "REJECTED"


def test_asf_055_observer_rejects_none() -> None:
    assert observer_scope_safety_receipt(None)["fail_closed"] is True


def test_asf_056_observer_never_promotes() -> None:
    out = observer_scope_safety_receipt(_observer())
    assert out["promotion"] is False and out["mutation"] is False

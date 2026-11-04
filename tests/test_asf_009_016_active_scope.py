from hl_observer.strategies.active_scope import (
    cloud_path_receipt, continuous_collection_receipt, copy_vault_only_receipt,
    experimental_flags_receipt, fail_closed_scope_receipt, lease_epoch_receipt,
    paper_read_only_scope_receipt, phase_contract_receipt,
)


def test_asf_009_paper_read_only():
    assert paper_read_only_scope_receipt({"PAPER_ONLY": True, "READ_ONLY": True, "LIVE_TRADING": False})["status"] == "PROVEN"


def test_asf_010_copy_vault_only():
    assert copy_vault_only_receipt(("copy_vault",))["status"] == "PROVEN"


def test_asf_011_flags_bounded():
    assert experimental_flags_receipt({})["status"] == "PROVEN"


def test_asf_012_fail_closed():
    assert fail_closed_scope_receipt("carry")["status"] == "PROVEN"


def test_asf_013_phase():
    assert phase_contract_receipt("ANALYZE", ("IDLE", "COLLECT", "ANALYZE"))["status"] == "PROVEN"


def test_asf_014_lease_epoch():
    assert lease_epoch_receipt(lease_epoch=2, phase_epoch=2, lease_active=True)["status"] == "PROVEN"


def test_asf_015_collection_continuity():
    assert continuous_collection_receipt(checkpoint_age_ms=10, max_age_ms=100, collection_active=True)["status"] == "PROVEN"


def test_asf_016_cloud_path():
    assert cloud_path_receipt(runner_kind="github-hosted", self_hosted=False, local_dependency=False)["status"] == "PROVEN"

from hl_observer.backtesting.copy_vault_evidence_inventory import (
    archive_member_path_receipt,
    archive_symlink_receipt,
    clone_completeness_receipt,
    destination_collision_receipt,
    disk_budget_receipt,
    download_completion_receipt,
    manifest_freshness_receipt,
    post_read_hash_receipt,
    resume_offset_receipt,
    windows_path_length_receipt,
)


def test_bug_241_interrupted_download_is_rejected():
    assert download_completion_receipt(downloaded_bytes=2, expected_bytes=2, stream_closed=True, digest_valid=True)["status"] == "PROVEN"
    assert download_completion_receipt(downloaded_bytes=1, expected_bytes=2, stream_closed=False, digest_valid=False)["status"] == "REJECTED"


def test_bug_242_resume_offset_is_exact():
    assert resume_offset_receipt(checkpoint_offset=4, resume_offset=4, total_bytes=8)["status"] == "PROVEN"
    assert resume_offset_receipt(checkpoint_offset=4, resume_offset=3, total_bytes=8)["status"] == "REJECTED"


def test_bug_243_archive_parent_traversal_is_rejected():
    assert archive_member_path_receipt(member_name="safe/file.json")["status"] == "PROVEN"
    assert archive_member_path_receipt(member_name="../outside.json")["status"] == "REJECTED"


def test_bug_244_archive_symlink_is_bounded():
    assert archive_symlink_receipt(is_symlink=False, target_within_workspace=False)["status"] == "PROVEN"
    assert archive_symlink_receipt(is_symlink=True, target_within_workspace=False)["status"] == "REJECTED"


def test_bug_245_extraction_respects_disk_budget():
    assert disk_budget_receipt(required_bytes=5, budget_bytes=6)["status"] == "PROVEN"
    assert disk_budget_receipt(required_bytes=7, budget_bytes=6)["status"] == "REJECTED"


def test_bug_246_hash_is_verified_after_read():
    assert post_read_hash_receipt(hash_before="a", hash_after="a", read_verified=True)["status"] == "PROVEN"
    assert post_read_hash_receipt(hash_before="a", hash_after="b", read_verified=True)["status"] == "REJECTED"


def test_bug_247_windows_path_length_is_bounded():
    assert windows_path_length_receipt(path="C:/safe/file", max_chars=260)["status"] == "PROVEN"
    assert windows_path_length_receipt(path="x" * 261, max_chars=260)["status"] == "REJECTED"


def test_bug_248_destinations_do_not_collide():
    assert destination_collision_receipt(source_ids=["a", "b"], destination_paths=["x", "y"])["status"] == "PROVEN"
    assert destination_collision_receipt(source_ids=["a", "b"], destination_paths=["x", "x"])["status"] == "REJECTED"


def test_bug_249_manifest_matches_current_revision():
    assert manifest_freshness_receipt(manifest_git_sha="a", current_git_sha="a")["status"] == "PROVEN"
    assert manifest_freshness_receipt(manifest_git_sha="a", current_git_sha="b")["status"] == "REJECTED"


def test_bug_250_partial_clone_is_rejected():
    assert clone_completeness_receipt(expected_commit="a", actual_commit="a", checkout_complete=True)["status"] == "PROVEN"
    assert clone_completeness_receipt(expected_commit="a", actual_commit="b", checkout_complete=False)["status"] == "REJECTED"

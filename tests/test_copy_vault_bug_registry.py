from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "audit" / "COPY_VAULT_BUG_REGISTRY.json"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_CI_STATES = {"PENDING", "NOT_RECONCILED", "PASSED", "FAILED"}
ALLOWED_LOCAL_STATUSES = {"NOT_RUN", "PASS", "FAIL"}


def test_copy_vault_bug_registry_keeps_traceable_red_green_evidence() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    assert registry["schema"] == "alina.copy_vault_bug_registry.v1"
    assert registry["economic_scope"] == "copy_vault_only"
    entries = registry["entries"]
    assert entries
    assert len({entry["id"] for entry in entries}) == len(entries)

    for entry in entries:
        assert entry["id"].startswith("CVB-")
        assert entry["priority"] in {"P0", "P1", "P2", "P3"}
        assert entry["status"] in {
            "FIXED_CODE_AWAITING_EXACT_SHA_VALIDATION",
            "FIXED_CODE_LOCAL_TESTS_PASS",
        }
        assert SHA_PATTERN.fullmatch(entry["first_seen_sha"])
        assert SHA_PATTERN.fullmatch(entry["fix_sha"])
        assert entry["root_cause"].strip()
        assert entry["red_evidence"]["test"].strip()
        assert entry["red_evidence"]["result"].strip()
        assert entry["fix_summary"].strip()
        assert entry["green_evidence"].strip()

        for component_path in entry["component_paths"]:
            assert (ROOT / component_path).is_file(), component_path

        for test_ref in entry["anti_regression_tests"]:
            test_path = test_ref.split("::", maxsplit=1)[0]
            assert (ROOT / test_path).is_file(), test_ref
            if "::" in test_ref:
                test_name = test_ref.split("::", maxsplit=1)[1]
                assert test_name in (ROOT / test_path).read_text(encoding="utf-8"), test_ref

        ci = entry["github_validation"]
        assert SHA_PATTERN.fullmatch(ci["target_sha"])
        assert ci["state"] in ALLOWED_CI_STATES
        if ci["state"] == "PASSED":
            assert ci["run_ids"]

        if entry["status"] == "FIXED_CODE_LOCAL_TESTS_PASS":
            local = entry["local_validation"]
            assert local["state"] == "PASS"
            assert SHA_PATTERN.fullmatch(local["base_head_sha"])
            assert local["target"] == "DIRTY_LOCAL_WORKING_TREE"
            assert local["working_tree_clean"] is False
            assert local["anti_regression_tests"] == entry["anti_regression_tests"]
            assert local["test_result"].strip()


def test_bug_registry_never_marks_unverified_fix_as_verified() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    for entry in registry["entries"]:
        if entry["github_validation"]["state"] != "PASSED":
            assert entry["status"] != "VERIFIED"


def test_local_validation_does_not_claim_a_github_hosted_result() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    for entry in registry["entries"]:
        local = entry.get("local_validation")
        assert local is not None
        assert local["state"] in ALLOWED_LOCAL_STATUSES
        if local["state"] == "PASS":
            assert entry["status"] == "FIXED_CODE_LOCAL_TESTS_PASS"
            assert entry["github_validation"]["state"] != "PASSED"

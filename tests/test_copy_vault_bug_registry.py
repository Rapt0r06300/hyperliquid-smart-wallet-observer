from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "audit" / "COPY_VAULT_BUG_REGISTRY.json"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_CI_STATES = {"PENDING", "NOT_RECONCILED", "PASSED", "FAILED"}


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
        assert entry["status"] == "FIXED_CODE_AWAITING_EXACT_SHA_VALIDATION"
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


def test_bug_registry_never_marks_unverified_fix_as_verified() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    for entry in registry["entries"]:
        if entry["github_validation"]["state"] != "PASSED":
            assert entry["status"] != "VERIFIED"

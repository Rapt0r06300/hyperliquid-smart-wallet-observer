from __future__ import annotations

import hashlib

from hl_observer.ops.pre_full_rehearsal import (
    FINAL_GO_FLAGS,
    ORDERED_STAGES,
    SCHEMA,
    evaluate_final_go,
    evaluate_rehearsals,
)


def _payload(go="FALSE"):
    return {
        "schema": SCHEMA,
        "project_sha": "a" * 40,
        "paper_only": True,
        "real_execution": False,
        "stages": [
            {"name": name, "status": "PASSED", "evidence_sha256": hashlib.sha256(name.encode()).hexdigest()}
            for name in ORDERED_STAGES
        ],
        "final_go": {**{flag: True for flag in FINAL_GO_FLAGS}, "GO_SELF_HOSTED": go},
    }


def test_ordered_rehearsals_require_every_stage_and_evidence():
    assert evaluate_rehearsals(_payload())["ok"] is True
    broken = _payload(); broken["stages"][3]["status"] = "SKIPPED"
    assert evaluate_rehearsals(broken)["ok"] is False


def test_final_go_requires_explicit_true_after_every_green_flag():
    assert evaluate_final_go(_payload("FALSE"))["go"] is False
    assert evaluate_final_go(_payload("TRUE"))["go"] is True

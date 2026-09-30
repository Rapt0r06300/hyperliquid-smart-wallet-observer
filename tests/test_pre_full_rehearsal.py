from __future__ import annotations

import hashlib

from hl_observer.ops.pre_full_rehearsal import (
    FINAL_GO_FLAGS,
    ORDERED_STAGES,
    SCHEMA,
    evaluate_final_go,
    evaluate_rehearsals,
)


def _payload(github_hosted_only=True):
    return {
        "schema": SCHEMA,
        "project_sha": "a" * 40,
        "paper_only": True,
        "real_execution": False,
        "stages": [
            {"name": name, "status": "PASSED", "evidence_sha256": hashlib.sha256(name.encode()).hexdigest()}
            for name in ORDERED_STAGES
        ],
        "final_go": {
            **{flag: True for flag in FINAL_GO_FLAGS},
            "github_hosted_only": github_hosted_only,
            "self_hosted_reachable": False,
            "user_pc_dependency": False,
        },
    }


def test_ordered_rehearsals_require_every_stage_and_evidence():
    assert evaluate_rehearsals(_payload())["ok"] is True
    broken = _payload(); broken["stages"][3]["status"] = "SKIPPED"
    assert evaluate_rehearsals(broken)["ok"] is False


def test_final_go_requires_github_hosted_only_and_no_pc_dependency():
    assert evaluate_final_go(_payload())["go"] is True
    not_hosted = _payload(False)
    assert evaluate_final_go(not_hosted)["go"] is False
    self_hosted = _payload()
    self_hosted["final_go"]["self_hosted_reachable"] = True
    assert evaluate_final_go(self_hosted)["go"] is False
    pc_bound = _payload()
    pc_bound["final_go"]["user_pc_dependency"] = True
    assert evaluate_final_go(pc_bound)["go"] is False

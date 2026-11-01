from __future__ import annotations

import pytest

from hl_observer.backtesting.copy_vault_hosted_receipt import (
    build_hosted_ci_receipt,
)
from hl_observer.backtesting.copy_vault_task_closure_plans import (
    TASK_IDS,
    task_closure_contract_sha256,
)

HEAD = "2c550287593c9578c36f534705f10511d9082d6c"


def _artifact(name: str, artifact_id: str) -> dict[str, str]:
    return {
        "id": artifact_id,
        "name": name,
        "digest": "sha256:" + "a" * 64,
    }


def _tasklist_report() -> dict[str, object]:
    return {
        "schema": "hypersmart.copy_vault_task_closure_plans.v1",
        "expected_head_sha": HEAD,
        "global": {
            "done": 0,
            "testing": 10,
            "blocked": 2,
            "total": 10,
            "closure_allowed": False,
        },
        "tasks": [
            {
                "task_id": task_id,
                "closure_contract_sha256": task_closure_contract_sha256(task_id),
            }
            for task_id in TASK_IDS
        ],
    }


def test_receipt_binds_ci_and_artifacts_without_overclaiming_task_closure() -> None:
    receipt = build_hosted_ci_receipt(
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        workflow="labo-continu-ci",
        event="workflow_dispatch",
        ref="refs/heads/codex/copyvault-evidence-709cf00",
        head_sha=HEAD,
        run_id="41305234537",
        run_attempt="1",
        status="completed",
        conclusion="success",
        pytest_exit_code=0,
        junit_artifact=_artifact(f"labo-continu-junit-41305234537-{HEAD}", "13082693608"),
        closure_artifact=_artifact(
            f"copy-vault-tasklist-closure-41305234537-{HEAD}", "13083406734",
        ),
        tasklist_report=_tasklist_report(),
    )

    assert receipt["proof_status"] == "HOSTED_CI_VERIFIED"
    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False
    assert receipt["tasklist"]["closure_allowed"] is False
    assert receipt["claims"]["exact_sha_bound_ci_receipt"] is True
    assert receipt["task_contract_sha256"]["H-T95"] == task_closure_contract_sha256("H-T95")
    assert "checkpoint_resume_proven" not in receipt["claims"]


def test_receipt_rejects_missing_digest_or_sha_bound_artifact_name() -> None:
    with pytest.raises(ValueError, match="artifact digest"):
        build_hosted_ci_receipt(
            repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
            workflow="labo-continu-ci",
            event="push",
            ref="refs/heads/main",
            head_sha=HEAD,
            run_id="1",
            run_attempt="1",
            status="completed",
            conclusion="success",
            pytest_exit_code=0,
            junit_artifact={
                "id": "1",
                "name": "labo-continu-junit-1",
                "digest": None,
            },
            closure_artifact=_artifact(f"copy-vault-tasklist-closure-1-{HEAD}", "2"),
            tasklist_report=_tasklist_report(),
        )

    with pytest.raises(ValueError, match="exact head SHA"):
        build_hosted_ci_receipt(
            repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
            workflow="labo-continu-ci",
            event="push",
            ref="refs/heads/main",
            head_sha=HEAD,
            run_id="1",
            run_attempt="1",
            status="completed",
            conclusion="success",
            pytest_exit_code=0,
            junit_artifact=_artifact("labo-continu-junit-1-wrong-sha", "1"),
            closure_artifact=_artifact(f"copy-vault-tasklist-closure-1-{HEAD}", "2"),
            tasklist_report=_tasklist_report(),
        )


def test_receipt_rejects_a_ten_row_report_for_the_wrong_tasks() -> None:
    report = _tasklist_report()
    report["tasks"] = [
        {"task_id": f"OTHER-{index}", "closure_contract_sha256": "b" * 64}
        for index in range(10)
    ]

    with pytest.raises(ValueError, match="exact Copy-Vault task IDs"):
        build_hosted_ci_receipt(
            repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
            workflow="labo-continu-ci",
            event="workflow_dispatch",
            ref="refs/heads/codex/copyvault-evidence-709cf00",
            head_sha=HEAD,
            run_id="41305234537",
            run_attempt="1",
            status="completed",
            conclusion="success",
            pytest_exit_code=0,
            junit_artifact=_artifact(f"labo-continu-junit-41305234537-{HEAD}", "1"),
            closure_artifact=_artifact(
                f"copy-vault-tasklist-closure-41305234537-{HEAD}", "2",
            ),
            tasklist_report=report,
        )


def test_receipt_rejects_closure_without_proven_rows() -> None:
    report = _tasklist_report()
    report["global"] = {
        "done": 10,
        "testing": 0,
        "blocked": 0,
        "total": 10,
        "closure_allowed": True,
    }

    with pytest.raises(ValueError, match="unproven task"):
        build_hosted_ci_receipt(
            repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
            workflow="labo-continu-ci",
            event="workflow_dispatch",
            ref="refs/heads/codex/copyvault-evidence-709cf00",
            head_sha=HEAD,
            run_id="41305234537",
            run_attempt="1",
            status="completed",
            conclusion="success",
            pytest_exit_code=0,
            junit_artifact=_artifact(f"labo-continu-junit-41305234537-{HEAD}", "1"),
            closure_artifact=_artifact(
                f"copy-vault-tasklist-closure-41305234537-{HEAD}", "2",
            ),
            tasklist_report=report,
        )

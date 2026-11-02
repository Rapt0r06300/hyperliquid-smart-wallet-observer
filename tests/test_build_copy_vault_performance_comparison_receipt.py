from __future__ import annotations

from tools.build_copy_vault_performance_comparison_receipt import build_receipt


def _arm(offset: int) -> dict[str, object]:
    runs = [
        {
            "trial": 1,
            "returncode": 0,
            "elapsed_ns": 1000 - offset,
            "stdout": "policy: OK\n",
            "stderr": "",
        },
        {
            "trial": 2,
            "returncode": 0,
            "elapsed_ns": 1100 - offset,
            "stdout": "policy: OK\n",
            "stderr": "",
        },
    ]
    return {
        "runs": runs,
        "median_elapsed_ns": 1050 - offset,
        "completed": True,
        "stdout_values": ["policy: OK\n", "policy: OK\n"],
        "stderr_values": ["", ""],
    }


def test_receipt_proves_only_same_context_reproducible_gain() -> None:
    receipt = build_receipt(
        {
            "baseline": _arm(0),
            "challenger": _arm(100),
            "same_dataset": True,
            "same_args": True,
            "arguments": [],
        },
        head_sha="a" * 40,
        baseline_ref="6942512540204",
        baseline_source_sha256="b" * 64,
        dataset_hashes={"index": "c" * 64},
        source_path="tools/check_dataset_quality.py",
        trials=2,
    )

    assert receipt["evidence_status"] == "VERIFIED"
    assert all(receipt["claims"].values())
    assert receipt["real_execution"] is False
    assert receipt["delta_usd_per_active_day"].startswith("NOT_MEASURED")


def test_receipt_rejects_non_deterministic_output() -> None:
    baseline = _arm(0)
    challenger = _arm(100)
    challenger["stdout_values"] = ["policy: OK\n", "policy: DIFFERENT\n"]
    receipt = build_receipt(
        {
            "baseline": baseline,
            "challenger": challenger,
            "same_dataset": True,
            "same_args": True,
            "arguments": [],
        },
        head_sha="a" * 40,
        baseline_ref="6942512540204",
        baseline_source_sha256="b" * 64,
        dataset_hashes={"index": "c" * 64},
        source_path="tools/check_dataset_quality.py",
        trials=2,
    )

    assert receipt["evidence_status"] == "NOT_PROVEN"
    assert "determinism_preserved" in receipt["missing_evidence"]
    assert "semantic_equivalence" in receipt["missing_evidence"]

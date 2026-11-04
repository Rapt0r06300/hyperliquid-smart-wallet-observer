from __future__ import annotations

from hl_observer.backtesting.copy_vault_closure_gate import (
    NOT_PROVEN,
    PROVEN,
    UNMEASURABLE,
    ClosureCriterion,
    EvidenceRecord,
    build_closure_matrix,
)

HEAD = "2c550287593c9578c36f534705f10511d9082d6c"


def _hosted(*, run_id: str = "run-1", artifact_id: str = "artifact-1", **claims: object) -> EvidenceRecord:
    return EvidenceRecord(
        kind="github_hosted",
        source=f"github://run/{run_id}/artifact/{artifact_id}",
        head_sha=HEAD,
        evidence_status="VERIFIED",
        paper_read_only=True,
        real_execution=False,
        run_id=run_id,
        artifact_id=artifact_id,
        run_status="completed",
        conclusion="success",
        artifact_sha256="a" * 64,
        claims=claims,
    )


def test_exact_sha_hosted_success_can_prove_a_criterion() -> None:
    report = build_closure_matrix(
        "H-T102",
        [
            ClosureCriterion(
                "exact_sha_hosted_run",
                ("github_hosted",),
                required_claims={"semantic_equivalence": True},
                require_hosted=True,
            )
        ],
        [_hosted(semantic_equivalence=True)],
        expected_head_sha=HEAD,
    )

    assert report["status"] == PROVEN
    assert report["recommended_agiflow_state"] == "Done"
    assert report["closure_allowed"] is True
    assert report["criteria"][0]["run_ids"] == ["run-1"]


def test_criterion_matrix_keeps_exact_proof_provenance() -> None:
    report = build_closure_matrix(
        "H-T102",
        [ClosureCriterion(
            "exact_sha_hosted_run",
            ("github_hosted",),
            required_claims={"semantic_equivalence": True},
            require_hosted=True,
        )],
        [_hosted(semantic_equivalence=True)],
        expected_head_sha=HEAD,
    )

    assert report["criteria"][0]["evidence_refs"] == [{
        "artifact_id": "artifact-1",
        "artifact_sha256": "a" * 64,
        "claims": {"semantic_equivalence": True},
        "conclusion": "success",
        "evidence_status": "VERIFIED",
        "head_sha": HEAD,
        "kind": "github_hosted",
        "paper_read_only": True,
        "real_execution": False,
        "result": "PROVEN",
        "run_id": "run-1",
        "run_status": "completed",
        "source": "github://run/run-1/artifact/artifact-1",
    }]


def test_criterion_matrix_keeps_rejected_proof_reasons() -> None:
    queued = EvidenceRecord(
        **{**_hosted(semantic_equivalence=True).__dict__, "run_status": "queued"},
    )
    report = build_closure_matrix(
        "H-T102",
        [ClosureCriterion("exact_sha_hosted_run", ("github_hosted",), require_hosted=True)],
        [queued],
        expected_head_sha=HEAD,
    )

    assert report["criteria"][0]["evidence_refs"][0]["result"] == "REJECTED"
    assert report["criteria"][0]["evidence_refs"][0]["reasons"] == [
        "HOSTED_RUN_NOT_COMPLETED",
    ]


def test_stale_rejected_receipt_does_not_poison_a_valid_current_receipt() -> None:
    stale = EvidenceRecord(
        **{**_hosted(semantic_equivalence=True).__dict__, "head_sha": "f" * 40},
    )
    current = _hosted(run_id="run-current", artifact_id="artifact-current", semantic_equivalence=True)
    report = build_closure_matrix(
        "H-T102",
        [ClosureCriterion("exact_sha_hosted_run", ("github_hosted",), require_hosted=True)],
        [stale, current],
        expected_head_sha=HEAD,
    )

    assert report["status"] == PROVEN
    assert report["closure_allowed"] is True
    assert report["criteria"][0]["run_ids"] == ["run-current"]
    assert any(ref["result"] == "REJECTED" for ref in report["criteria"][0]["evidence_refs"])
    assert not any("EXACT_SHA_MISMATCH" in item for item in report["missing_evidence"])


def test_queued_or_wrong_sha_evidence_cannot_close_a_criterion() -> None:
    queued = _hosted(semantic_equivalence=True)
    queued = EvidenceRecord(
        **{**queued.__dict__, "run_status": "in_progress"},
    )
    wrong_sha = EvidenceRecord(
        **{**_hosted(semantic_equivalence=True).__dict__, "head_sha": "f" * 40},
    )
    report = build_closure_matrix(
        "H-T102",
        [ClosureCriterion("exact_sha_hosted_run", ("github_hosted",), require_hosted=True)],
        [queued, wrong_sha],
        expected_head_sha=HEAD,
    )

    assert report["status"] == NOT_PROVEN
    assert report["recommended_agiflow_state"] == "Testing"
    assert report["closure_allowed"] is False
    assert any("HOSTED_RUN_NOT_COMPLETED" in item for item in report["missing_evidence"])
    assert any("EXACT_SHA_MISMATCH" in item for item in report["missing_evidence"])


def test_omitted_safety_flags_fail_closed() -> None:
    raw = _hosted(semantic_equivalence=True).__dict__.copy()
    raw.pop("real_execution")
    raw.pop("paper_read_only")
    report = build_closure_matrix(
        "H-T102",
        [ClosureCriterion("exact_sha_hosted_run", ("github_hosted",), require_hosted=True)],
        [EvidenceRecord.from_mapping(raw)],
        expected_head_sha=HEAD,
    )

    assert report["status"] == NOT_PROVEN
    assert (
        "exact_sha_hosted_run:github_hosted:PAPER_READ_ONLY_REQUIRED"
        in report["missing_evidence"]
    )
    assert (
        "exact_sha_hosted_run:github_hosted:REAL_EXECUTION_MUST_BE_FALSE"
        in report["missing_evidence"]
    )


def test_sample_restore_is_not_full_dataset_proof() -> None:
    report = build_closure_matrix(
        "H-T195",
        [
            ClosureCriterion(
                "full_safe_restore",
                ("github_hosted",),
                require_hosted=True,
                require_full_dataset=True,
            )
        ],
        [_hosted(full_dataset_certified=False)],
        expected_head_sha=HEAD,
    )

    assert report["status"] == NOT_PROVEN
    assert (
        "full_safe_restore:github_hosted:FULL_DATASET_CERTIFICATION_MISSING"
        in report["missing_evidence"]
    )


def test_missing_causal_data_remains_unmeasurable() -> None:
    report = build_closure_matrix(
        "H-T170",
        [
            ClosureCriterion(
                "causal_live_fill",
                ("safe_replay",),
                required_claims={"causal_live_fill_rows": {"min": 1}},
                unavailable_is_unmeasurable=True,
            )
        ],
        [
            EvidenceRecord(
                kind="safe_replay",
                source="local://safe-replay-receipt.json",
                head_sha=HEAD,
                evidence_status="VERIFIED",
                paper_read_only=True,
                real_execution=False,
                claims={"causal_live_fill_rows": 0},
            )
        ],
        expected_head_sha=HEAD,
    )

    assert report["status"] == UNMEASURABLE
    assert report["recommended_agiflow_state"] == "Testing"
    assert (
        "causal_live_fill:safe_replay:CLAIM_MISMATCH:causal_live_fill_rows"
        in report["missing_evidence"]
    )


def test_two_hosted_runs_require_two_distinct_run_ids() -> None:
    criterion = ClosureCriterion(
        "two_exact_sha_retries",
        ("github_hosted",),
        require_hosted=True,
        min_distinct_runs=2,
    )
    one_run = build_closure_matrix(
        "H-T195", [criterion], [_hosted()], expected_head_sha=HEAD,
    )
    two_runs = build_closure_matrix(
        "H-T195",
        [criterion],
        [_hosted(), _hosted(run_id="run-2", artifact_id="artifact-2")],
        expected_head_sha=HEAD,
    )

    assert one_run["status"] == NOT_PROVEN
    assert two_runs["status"] == PROVEN
    assert two_runs["criteria"][0]["run_ids"] == ["run-1", "run-2"]


def test_hosted_evidence_requires_a_verified_artifact_digest() -> None:
    record = EvidenceRecord(
        **{**_hosted(semantic_equivalence=True).__dict__, "artifact_sha256": None},
    )
    report = build_closure_matrix(
        "H-T102",
        [ClosureCriterion("exact_sha_hosted_run", ("github_hosted",), require_hosted=True)],
        [record],
        expected_head_sha=HEAD,
    )

    assert report["status"] == NOT_PROVEN
    assert (
        "exact_sha_hosted_run:github_hosted:HOSTED_ARTIFACT_DIGEST_MISSING"
        in report["missing_evidence"]
    )


def test_two_hosted_runs_cannot_reuse_one_artifact() -> None:
    criterion = ClosureCriterion(
        "two_exact_sha_retries",
        ("github_hosted",),
        require_hosted=True,
        min_distinct_runs=2,
    )
    reused_artifact = build_closure_matrix(
        "H-T195",
        [criterion],
        [
            _hosted(run_id="run-1", artifact_id="same-artifact"),
            _hosted(run_id="run-2", artifact_id="same-artifact"),
        ],
        expected_head_sha=HEAD,
    )

    assert reused_artifact["status"] == NOT_PROVEN
    assert (
        "two_exact_sha_retries:DISTINCT_ARTIFACTS_INSUFFICIENT:1<2"
        in reused_artifact["missing_evidence"]
    )


def test_hosted_evidence_rejects_blank_run_and_artifact_ids() -> None:
    record = EvidenceRecord(
        **{
            **_hosted(semantic_equivalence=True).__dict__,
            "run_id": "",
            "artifact_id": "",
        },
    )
    report = build_closure_matrix(
        "H-T102",
        [ClosureCriterion("exact_sha_hosted_run", ("github_hosted",), require_hosted=True)],
        [record],
        expected_head_sha=HEAD,
    )

    assert report["status"] == NOT_PROVEN
    reasons = report["missing_evidence"]
    assert "exact_sha_hosted_run:github_hosted:HOSTED_RUN_ID_MISSING" in reasons
    assert "exact_sha_hosted_run:github_hosted:HOSTED_ARTIFACT_ID_MISSING" in reasons


def test_numeric_claim_bounds_reject_nan_and_non_numeric_values() -> None:
    criterion = ClosureCriterion(
        "causal_rows",
        ("safe_replay",),
        required_claims={"rows": {"min": 1}},
    )
    base = EvidenceRecord(
        kind="safe_replay",
        source="local://safe-replay.json",
        head_sha=HEAD,
        evidence_status="VERIFIED",
        paper_read_only=True,
        real_execution=False,
    )
    nan_report = build_closure_matrix(
        "H-T170",
        [criterion],
        [EvidenceRecord(**{**base.__dict__, "claims": {"rows": float("nan")}})],
        expected_head_sha=HEAD,
    )
    string_report = build_closure_matrix(
        "H-T170",
        [criterion],
        [EvidenceRecord(**{**base.__dict__, "claims": {"rows": "1"}})],
        expected_head_sha=HEAD,
    )

    assert nan_report["status"] == NOT_PROVEN
    assert string_report["status"] == NOT_PROVEN


def test_criterion_rejects_boolean_run_count() -> None:
    try:
        build_closure_matrix(
            "H-T195",
            [ClosureCriterion("two_runs", ("github_hosted",), min_distinct_runs=True)],
            [_hosted()],
            expected_head_sha=HEAD,
        )
    except ValueError as exc:
        assert "min_distinct_runs" in str(exc)
    else:
        raise AssertionError("boolean min_distinct_runs must fail closed")


def test_criterion_rejects_non_finite_or_inverted_claim_bounds() -> None:
    base = {"kind": "safe_replay", "source": "local://receipt", "head_sha": HEAD,
            "evidence_status": "VERIFIED", "paper_read_only": True, "real_execution": False}
    for claims in ({"rows": {"min": float("nan")}}, {"rows": {"min": 3, "max": 2}}):
        try:
            build_closure_matrix(
                "H-T170",
                [ClosureCriterion("rows", ("safe_replay",), required_claims=claims)],
                [EvidenceRecord(**base, claims={"rows": 3})],
                expected_head_sha=HEAD,
            )
        except ValueError as exc:
            assert "rows" in str(exc)
        else:
            raise AssertionError("invalid claim bounds must fail closed")

from tools.validate_campaign_resilience import _unit_requires_publication_receipt


def test_continuation_checkpoint_does_not_require_publication_receipt():
    unit = {
        "sha256": "a" * 64,
        "result": {
            "status": "CONTINUATION_REQUIRED",
            "reason": "resume_proof_selection_checkpoint",
        },
    }
    assert _unit_requires_publication_receipt(unit) is False


def test_complete_unit_requires_publication_receipt():
    unit = {
        "sha256": "b" * 64,
        "result": {
            "status": "COMPLETE",
            "durable_persisted": True,
            "evidence_release_tag": "campaign-evidence-example-u1",
        },
    }
    assert _unit_requires_publication_receipt(unit) is True


def test_malformed_unit_does_not_create_false_publication_requirement():
    assert _unit_requires_publication_receipt(None) is False
    assert _unit_requires_publication_receipt({}) is False

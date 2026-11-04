from hl_observer.ops.document_authority import (
    architecture_surface_receipt, authority_hierarchy_receipt,
    complementary_ideas_receipt, coverage_matrix_receipt,
    documentation_reconciliation_receipt, head_identity_receipt,
    historical_requirements_receipt, version_reconciliation_receipt,
)


SHA = "a" * 40


def test_asf_001_head():
    assert head_identity_receipt(branch="main", local_head=SHA, remote_head=SHA, true_head=SHA)["status"] == "PROVEN"


def test_asf_002_authority():
    assert authority_hierarchy_receipt(required_documents=("SECURITY.md",), present_documents=("SECURITY.md",))["status"] == "PROVEN"


def test_asf_003_architecture():
    assert architecture_surface_receipt(runtime_path="src/hl_observer", legacy_path="hyper_smart_observer", canonical_runtime="src/hl_observer")["status"] == "PROVEN"


def test_asf_004_history():
    assert historical_requirements_receipt(required_count=775, mapped_count=775, duplicate_count=0)["status"] == "PROVEN"


def test_asf_005_versions():
    assert version_reconciliation_receipt(prior_count=775, current_count=776, conflict_count=0)["status"] == "PROVEN"


def test_asf_006_ideas():
    assert complementary_ideas_receipt(idea_ids=("i1",), classified_ids=("i1",))["status"] == "PROVEN"


def test_asf_007_matrix():
    assert coverage_matrix_receipt(requirement_ids=("r1",), covered_ids=("r1",), duplicate_ids=())["status"] == "PROVEN"


def test_asf_008_docs():
    assert documentation_reconciliation_receipt(required_markers=("scope",), observed_markers=("scope",))["status"] == "PROVEN"

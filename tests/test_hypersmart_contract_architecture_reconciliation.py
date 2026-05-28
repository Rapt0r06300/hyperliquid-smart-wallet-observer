import pytest
import os

@pytest.mark.contract
def test_contract_architecture_dual_presence():
    """
    Contract: Both architectures must coexist for reconciliation.
    """
    assert os.path.isdir("hyper_smart_observer"), "Contract: hyper_smart_observer directory must exist"
    assert os.path.isdir("src/hl_observer"), "Contract: src/hl_observer directory must exist"

@pytest.mark.contract
def test_contract_reconciliation_doc_exists():
    """
    Contract: Reconciliation document must exist.
    """
    assert os.path.exists("docs/release/HYPERSMART_ARCHITECTURE_RECONCILIATION.md"), \
        "Contract: HYPERSMART_ARCHITECTURE_RECONCILIATION.md must exist"

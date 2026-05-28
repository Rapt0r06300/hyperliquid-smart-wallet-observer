import pytest
import os

@pytest.mark.contract
def test_contract_archive_button_exists():
    """
    Contract: The archive button (CMD) must exist at root.
    """
    assert os.path.exists("CREER_ARCHIVE_PROPRE.cmd"), "Contract: CREER_ARCHIVE_PROPRE.cmd must exist at root"

@pytest.mark.contract
def test_contract_archive_tools_exist():
    """
    Contract: Archive tools must exist in tools/.
    """
    assert os.path.exists("tools/create_clean_archive.ps1"), "Contract: tools/create_clean_archive.ps1 must exist"
    assert os.path.exists("tools/create_clean_archive.py"), "Contract: tools/create_clean_archive.py must exist"

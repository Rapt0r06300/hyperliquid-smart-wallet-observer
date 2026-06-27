from __future__ import annotations

from hyper_smart_observer.models.common_data_model import (
    CDM_REQUIRED_OBJECTS,
    REQUIRED_METADATA_GROUPS,
    audit_common_data_model_contracts,
)


def test_common_data_model_required_metadata():
    report = audit_common_data_model_contracts()

    assert tuple(contract.name for contract in report.contracts) == CDM_REQUIRED_OBJECTS
    assert report.missing_objects == ()
    assert report.incomplete_objects == {}
    assert report.is_complete
    assert {contract.status for contract in report.contracts} <= {"IMPLEMENTED", "CONTRACTED"}


def test_common_data_model_endpoint_channel_and_raw_aliases():
    report = audit_common_data_model_contracts()

    for contract in report.contracts:
        fields = set(contract.metadata_fields)
        for alternatives in REQUIRED_METADATA_GROUPS:
            assert any(field in fields for field in alternatives), contract.name
        assert ("source_endpoint" in fields) or ("source_channel" in fields)
        assert ("raw_ref" in fields) or ("raw_hash" in fields)
        assert contract.implemented_by.startswith("hyper_smart_observer.")

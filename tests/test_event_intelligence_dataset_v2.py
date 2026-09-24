from __future__ import annotations

import json
from pathlib import Path

from hl_observer.event_intelligence.dataset_v2 import build_public_event_bundle
from hl_observer.event_intelligence.integration_registry import (
    EVENT_INTELLIGENCE_INTEGRATION,
    integration_contract,
)


class _DirectSourceClient:
    def get_json(self, source_id: str, *, params=None, api_key: str = ""):
        assert not api_key
        payloads = {
            "usgs_earthquakes": {
                "features": [
                    {
                        "id": "quake-1",
                        "properties": {
                            "mag": 6.0,
                            "time": 900,
                            "updated": 950,
                            "place": "Test Region",
                            "url": "https://example.test/q",
                        },
                    }
                ]
            },
            "nasa_eonet": {
                "events": [
                    {
                        "id": "eonet-1",
                        "link": "https://example.test/e",
                        "categories": [{"id": "severeStorms"}],
                        "geometry": [{"date": "1970-01-01T00:00:00.900Z"}],
                    }
                ]
            },
            "gdacs": {
                "features": [
                    {
                        "properties": {
                            "eventid": "gdacs-1",
                            "eventtype": "TC",
                            "alertlevel": "Red",
                            "country": "Testland",
                            "fromdate": "1970-01-01T00:00:00.800+00:00",
                        }
                    }
                ]
            },
            "gdelt_doc": {
                "articles": [
                    {
                        "url": "https://example.test/news",
                        "seendate": "19700101T000000Z",
                        "domain": "example.test",
                        "language": "English",
                    }
                ]
            },
        }
        return payloads[source_id]


def test_all_120_ideas_are_bound_to_runtime_modules_and_dataset_families() -> None:
    assert len(EVENT_INTELLIGENCE_INTEGRATION) == 120
    assert {row.idea_id for row in EVENT_INTELLIGENCE_INTEGRATION} == set(range(1, 121))
    assert all(row.strategy_families for row in EVENT_INTELLIGENCE_INTEGRATION)
    assert all(row.dataset_families for row in EVENT_INTELLIGENCE_INTEGRATION)

    contract = integration_contract()
    assert contract["idea_count"] == 120
    assert contract["coverage_complete"] is True
    assert contract["linked_strategy_families"] == [
        "arbitrage",
        "copy_vault",
        "cross_venue_dislocation",
        "lead_lag",
    ]
    assert len(contract["coverage_sha256"]) == 64
    assert contract["proof_state"] == "STRUCTURAL_ONLY"
    assert contract["proof_of_pnl_allowed"] is False


def test_public_event_bundle_is_causal_read_only_and_not_artificially_safe(
    tmp_path: Path,
) -> None:
    bundle = build_public_event_bundle(
        output_root=tmp_path / "bundle",
        collector_version="a" * 40,
        collection_run_id="event-test",
        client=_DirectSourceClient(),
        received_ts_ms=1_000,
        monotonic_ns=5_000,
    )

    assert bundle["shard_count"] == 4
    assert bundle["safe_count"] == 0
    assert bundle["partial_count"] == 4
    assert bundle["read_only"] is True
    assert bundle["real_execution"] is False
    assert bundle["event_intelligence"]["idea_count"] == 120

    manifests = []
    for relative in bundle["manifests"]:
        manifest = json.loads((tmp_path / "bundle" / relative).read_text(encoding="utf-8"))
        manifests.append(manifest)
        assert manifest["family"] == "external_events"
        assert manifest["quality_status"] == "PARTIAL"
        assert manifest["validation_allowed"] is False
        assert manifest["proof_of_pnl_allowed"] is False
        assert manifest["reconciliation"]["status"] == "UNAVAILABLE"
        assert manifest["reconciliation"]["reason"] == "NO_INDEPENDENT_EXACT_REFERENCE"
        assert manifest["event_intelligence"]["idea_count"] == 120
        assert manifest["event_intelligence"]["proof_state"] == "STRUCTURAL_ONLY"
        assert manifest["provenance"]["public_data_only"] is True
        assert manifest["provenance"]["authenticated"] is False
        assert manifest["provenance"]["real_execution"] is False
        assert manifest["integrity"]["missing_monotonic_count"] == 0
        assert manifest["integrity"]["missing_timestamp_count"] == 0
        assert manifest["synchronization"]["first_exchange_ts_ms"] is None

    assert {row["source"] for row in manifests} == {
        "gdacs",
        "gdelt.doc",
        "nasa.eonet",
        "usgs.earthquakes",
    }


def test_public_event_bundle_refuses_false_success_when_every_source_fails(tmp_path: Path) -> None:
    class _Broken:
        def get_json(self, source_id: str, *, params=None, api_key: str = ""):
            raise RuntimeError(f"down:{source_id}")

    try:
        build_public_event_bundle(
            output_root=tmp_path / "bundle",
            collector_version="b" * 40,
            collection_run_id="event-empty",
            client=_Broken(),
            received_ts_ms=1_000,
            monotonic_ns=5_000,
        )
    except RuntimeError as exc:
        assert str(exc) == "NO_EVENT_INTELLIGENCE_DATA"
    else:
        raise AssertionError("an all-source failure must not publish an empty success")

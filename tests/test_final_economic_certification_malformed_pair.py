from __future__ import annotations

from hl_observer.ops import final_economic_certification as certification


def test_certify_workspace_ignores_malformed_cross_family_pair_key(
    monkeypatch, tmp_path
) -> None:
    campaign = {
        "oos": {"sample_count": 1},
        "forward": {"sample_count": 1},
    }

    monkeypatch.setattr(certification, "_load_object", lambda _path: campaign)
    monkeypatch.setattr(
        certification,
        "certify_campaign",
        lambda family, _payload: {
            "family": family,
            "certified": True,
            "reasons": [],
        },
    )
    monkeypatch.setattr(certification, "_raw_trade_rows", lambda _family, _raw: [])
    monkeypatch.setattr(
        certification,
        "proof_events",
        lambda _rows: {
            "proof_rows": 2,
            "canonical_events": 2,
            "missing_identity_rows": 0,
            "duplicate_global_events": 0,
            "complete": True,
        },
    )
    monkeypatch.setattr(
        certification,
        "audit_family_event_sets",
        lambda _audits: {
            "no_reuse": True,
            "intra_family_duplicate_global_events": {},
            "pairwise": {
                "malformed-pair-key": {
                    "collision_count": 1,
                    "collision_ids": ["synthetic-proof-id"],
                }
            },
            "total_cross_family_collisions": 0,
        },
    )

    result = certification.certify_workspace(tmp_path)

    assert result["all_families_certified"] is True
    assert result["paper_only"] is True
    assert result["real_execution"] is False
    assert all(
        "CROSS_FAMILY_TRADE_REUSE" not in row["reasons"]
        for row in result["families"].values()
    )

from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.self_hosted_return import build_return, compact_campaign, write_return


FAMILIES = ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")


def test_compact_campaign_n_expose_pas_les_payloads_bruts() -> None:
    compact = compact_campaign(
        {
            "objective_status": "ATTEINT",
            "net_pnl_usd": 4.5,
            "signal_count": 42,
            "objective_reasons": ["OK"],
            "raw_json": {"secret": "ne doit pas sortir"},
            "fills": [1, 2, 3],
        }
    )
    assert compact["net_pnl_usd"] == 4.5
    assert compact["signal_count"] == 42
    assert compact["objective_reasons"] == ["OK"]
    assert "raw_json" not in compact
    assert "fills" not in compact


def test_build_return_resume_les_trois_familles_et_le_prochain_job(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    campaign_dir = workspace / "runtime" / "reports" / "economic_campaigns"
    campaign_dir.mkdir(parents=True)

    for index, family in enumerate(FAMILIES, start=1):
        (campaign_dir / f"{family}.json").write_text(
            json.dumps(
                {
                    "objective_status": "ATTEINT" if index == 1 else "NON_ATTEINT",
                    "net_pnl_usd": 4.25 if index == 1 else -0.5 * index,
                    "signal_count": 20 + index,
                    "objective_reasons": [] if index == 1 else ["TARGET_NET_USD_NOT_REACHED"],
                }
            ),
            encoding="utf-8",
        )

    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "JOB_RESULT.json").write_text(
        json.dumps(
            {
                "job_id": "job-retour-001",
                "status": "SUCCESS",
                "suite": "economic-full",
                "mode": "economic",
                "project_sha": "a" * 40,
                "request_digest": "b" * 64,
                "workspace": str(workspace),
                "exit_code": 0,
            }
        ),
        encoding="utf-8",
    )

    payload = build_return(result_dir)
    assert payload["status"] == "READY_FOR_ANALYSIS"
    assert payload["technical_status"] == "SUCCESS"
    assert payload["family_summaries"]["copy_vault"]["net_pnl_usd"] == 4.25
    assert payload["family_summaries"]["lead_lag"]["net_pnl_usd"] == -1.0
    assert payload["family_summaries"]["cross_venue_dislocation_v2"]["net_pnl_usd"] == -1.5
    assert payload["brain_decision"] is not None
    assert payload["next_recommended_job"] is not None
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False

    json_path, md_path = write_return(result_dir, payload)
    assert json_path.is_file()
    assert md_path.is_file()
    text = md_path.read_text(encoding="utf-8")
    assert "copy_vault" in text
    assert "lead_lag" in text
    assert "cross_venue_dislocation_v2" in text


def test_build_return_reste_explicite_si_job_result_absent(tmp_path: Path) -> None:
    payload = build_return(tmp_path)
    assert payload["status"] == "RESULT_MISSING"
    assert payload["technical_status"] == "NO_GO"
    assert payload["next_recommended_job"] is None
    assert all(value is None for value in payload["family_summaries"].values())


def test_raisons_sont_bornees() -> None:
    compact = compact_campaign(
        {
            "objective_reasons": ["x" * 1000 for _ in range(100)],
        }
    )
    assert len(compact["objective_reasons"]) == 50
    assert all(len(value) == 500 for value in compact["objective_reasons"])

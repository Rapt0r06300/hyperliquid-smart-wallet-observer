from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.ops import self_hosted_return as returner
from hl_observer.ops.self_hosted_return import (
    build_return,
    compact_campaign,
    load_family_summaries,
    write_return,
)


FAMILIES = ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")


def _job_result(result_dir: Path, *, workspace: Path | None) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "JOB_RESULT.json").write_text(
        json.dumps(
            {
                "job_id": "job-retour-001",
                "status": "SUCCESS",
                "suite": "economic-full",
                "mode": "economic",
                "project_sha": "a" * 40,
                "request_digest": "b" * 64,
                "workspace": str(workspace) if workspace is not None else None,
                "exit_code": 0,
            }
        ),
        encoding="utf-8",
    )


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
    assert compact["oos"] is None
    assert compact["forward"] is None
    assert compact["placebos"] is None
    assert "raw_json" not in compact
    assert "fills" not in compact


def test_compact_campaign_segments_et_placebo_sont_bornes() -> None:
    compact = compact_campaign(
        {
            "objective_reasons": ["", "  cause  "],
            "oos": {
                "sample_count": 2,
                "gross_pnl_usd": 1.4,
                "fees_usd": 0.1,
                "spread_cost_usd": 0.1,
                "slippage_cost_usd": 0.1,
                "latency_cost_usd": 0.1,
                "net_pnl_usd": 1.0,
                "LIQUIDATABLE_NET": True,
                "duplicate_trade_ids": 0,
                "trade_ids_count": 2,
                "no_lookahead": True,
                "raw": [1, 2, 3],
            },
            "forward": {
                "sample_count": 2,
                "net_pnl_usd": 1.0,
                "post_freeze": True,
            },
            "placebos": {"beaten": True, "raw": "secret"},
        }
    )
    assert compact["objective_reasons"] == ["cause"]
    assert compact["oos"]["no_lookahead"] is True
    assert compact["oos"]["LIQUIDATABLE_NET"] is True
    assert "raw" not in compact["oos"]
    assert compact["forward"]["post_freeze"] is True
    assert compact["placebos"] == {"beaten": True}


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
    _job_result(result_dir, workspace=workspace)

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
    assert "Certification économique 3/3 : **NON**" in text


def test_build_return_reste_explicite_si_job_result_absent(tmp_path: Path) -> None:
    payload = build_return(tmp_path)
    assert payload["status"] == "RESULT_MISSING"
    assert payload["technical_status"] == "NO_GO"
    assert payload["economic_certification"] is None
    assert payload["next_recommended_job"] is None
    assert all(value is None for value in payload["family_summaries"].values())


def test_workspace_absent_ne_produit_aucune_preuve_economique(tmp_path: Path) -> None:
    result_dir = tmp_path / "result"
    missing_workspace = tmp_path / "absent"
    _job_result(result_dir, workspace=missing_workspace)
    payload = build_return(result_dir)
    assert payload["workspace_available"] is False
    assert payload["economic_certification"] is None
    assert payload["brain_decision"] is None
    assert payload["next_recommended_job"] is None
    assert all(value is None for value in payload["family_summaries"].values())


def test_load_family_summaries_none_est_fail_closed() -> None:
    assert load_family_summaries(None) == {family: None for family in FAMILIES}


def test_build_return_message_3_sur_3_uniquement_apres_certification_recalculee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    campaign_dir = workspace / "runtime" / "reports" / "economic_campaigns"
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "copy_vault.json").write_text("{}", encoding="utf-8")
    result_dir = tmp_path / "result"
    _job_result(result_dir, workspace=workspace)

    monkeypatch.setattr(
        returner,
        "certify_workspace",
        lambda root: {
            "all_families_certified": True,
            "families": {family: {"status": "CERTIFIED"} for family in FAMILIES},
        },
    )
    monkeypatch.setattr(
        returner,
        "build_decision",
        lambda root: {
            "next_recommended_job": {
                "suite": "economic-full",
                "mode": "historical-full",
                "top_family": "copy_vault",
                "reason": "confirmation",
            }
        },
    )
    payload = build_return(result_dir)
    assert payload["economic_certification"]["all_families_certified"] is True
    assert "trois familles sont certifiées séparément" in payload["message_fr"]
    _, md_path = write_return(result_dir, payload)
    assert "Certification économique 3/3 : **OUI**" in md_path.read_text(encoding="utf-8")


def test_build_return_ne_masque_pas_une_erreur_du_cerveau(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    campaign_dir = workspace / "runtime" / "reports" / "economic_campaigns"
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "lead_lag.json").write_text("{}", encoding="utf-8")
    result_dir = tmp_path / "result"
    _job_result(result_dir, workspace=workspace)
    monkeypatch.setattr(returner, "build_decision", lambda root: (_ for _ in ()).throw(ValueError("bad")))
    payload = build_return(result_dir)
    assert payload["brain_decision"] is None
    assert payload["next_recommended_job"] is None


def test_write_return_affiche_famille_non_mesuree_et_aucun_next_job(tmp_path: Path) -> None:
    payload = {
        "job_id": "x",
        "technical_status": "NO_GO",
        "suite": "economic-full",
        "mode": "economic",
        "project_sha": "a" * 40,
        "economic_certification": None,
        "family_summaries": {family: None for family in FAMILIES},
        "next_recommended_job": None,
    }
    _, md_path = write_return(tmp_path, payload)
    text = md_path.read_text(encoding="utf-8")
    assert text.count("`NON_MESURE`") == 3
    assert "Aucune recommandation machine-lisible disponible" in text


def test_raisons_sont_bornees() -> None:
    compact = compact_campaign(
        {
            "objective_reasons": ["x" * 1000 for _ in range(100)],
        }
    )
    assert len(compact["objective_reasons"]) == 50
    assert all(len(value) == 500 for value in compact["objective_reasons"])
    assert compact_campaign({"objective_reasons": "pas-une-liste"})["objective_reasons"] == []


def test_main_retourne_4_sans_job_et_0_avec_job(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert returner.main(["--result-dir", str(missing)]) == 4
    result_dir = tmp_path / "result"
    _job_result(result_dir, workspace=None)
    assert returner.main(["--result-dir", str(result_dir)]) == 0
    assert (result_dir / "ALINA_RETURN.json").is_file()

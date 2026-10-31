from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tools" / "run_economic_objective_campaigns.py"
SPEC = importlib.util.spec_from_file_location("copy_vault_campaign_scope_runner", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class _CopyTool:
    def charger_entrees_alpha_avec_audit(self, _root):
        return [], {"rows": 0}

    def charger_entrees_alpha_notional_fixe_avec_audit(self, _root):
        return [], {"rows": 0}

    def charger_evenements_lifecycle_avec_audit(self, _root):
        return [], {"rows": 0}


def test_campagne_canonique_nexecute_que_copy_vault(tmp_path: Path, monkeypatch) -> None:
    loaded_tools: list[str] = []
    monkeypatch.setattr(runner, "_environment_provenance", lambda _root: {})
    monkeypatch.setattr(runner, "is_dataset_workspace", lambda _root: False)
    monkeypatch.setattr(runner, "dataset_provenance", lambda _root, _paths: {})
    monkeypatch.setattr(
        runner,
        "_tool",
        lambda name, _path: loaded_tools.append(name) or _CopyTool(),
    )
    monkeypatch.setattr(
        runner.copy_vault_executable,
        "cluster_metaorders",
        lambda _rows: ([], {"metaorders": 0}),
    )
    monkeypatch.setattr(
        runner.copy_vault_executable,
        "load_observed_books",
        lambda _root, *, coins: ({}, {"coins": sorted(coins)}),
    )
    protocol_audit = {
        "historical_or_noncausal_metaorders_excluded": 0,
        "protocol_scope": "test",
        "causal_protocol_book_rows": 0,
        "causal_protocol_coins": [],
        "historical_or_noncausal_book_rows_excluded": 0,
    }
    monkeypatch.setattr(
        runner.copy_vault_executable,
        "select_causal_protocol_inputs",
        lambda _metaorders, _books: ([], {}, dict(protocol_audit)),
    )
    monkeypatch.setattr(runner.copy_vault_executable, "protocol_signature", lambda: {})
    monkeypatch.setattr(
        runner.copy_vault_executable,
        "evaluate_frozen",
        lambda *_args, **_kwargs: {"trades": {}, "bounds": {}, "combined_summary": {}},
    )
    monkeypatch.setattr(runner.copy_vault_executable, "temporal_evidence", lambda _result: {})
    for name in (
        "explore_copy_vault_v4_train",
        "explore_copy_vault_v5_train",
        "explore_copy_vault_v6_balanced_train",
        "explore_copy_vault_v7_exit_flow_train",
        "explore_copy_vault_v8_entry_efficiency_train",
        "explore_copy_vault_v9_online_leader_quality_train",
    ):
        monkeypatch.setattr(runner, name, lambda *_args, **_kwargs: {"status": "TRAIN_ONLY"})
    monkeypatch.setattr(
        runner,
        "find_oldest_parameter_freeze",
        lambda *_args, **_kwargs: {"parameters": {}, "frozen_at_ms": 100},
    )
    monkeypatch.setattr(runner, "qualify_copy_vault_train_only", lambda _trades: {})
    monkeypatch.setattr(
        runner,
        "build_copy_campaign",
        lambda *_args, **_kwargs: {"family": "copy_vault", "evidence_paths": []},
    )
    monkeypatch.setattr(runner, "write_campaign", lambda *_args, **_kwargs: tmp_path / "campaign.json")
    monkeypatch.setattr(runner, "export_scoreboards", lambda _root: tmp_path / "scoreboard.json")
    monkeypatch.setattr(runner, "render_campaign_report", lambda _campaigns: "Copy-Vault only\n")
    monkeypatch.setattr(runner, "inspect_bounded_collectors", lambda _root: {})
    monkeypatch.setattr(runner, "build_collection_plan", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        runner,
        "write_collection_plan",
        lambda _root, _plan: (tmp_path / "collection.json", tmp_path / "collection.md"),
    )

    result = runner.run_campaigns(tmp_path)

    assert loaded_tools == ["hypersmart_copy_pipeline"]
    assert [campaign["family"] for campaign in result["campaigns"]] == ["copy_vault"]
    assert result["active_families"] == ["copy_vault"]
    assert set(result["disabled_families"]) == {"lead_lag", "cross_venue_dislocation_v2"}


def test_runner_refuse_un_scope_elargi_avant_de_charger_un_moteur(tmp_path: Path, monkeypatch) -> None:
    loaded_tools: list[str] = []
    monkeypatch.setattr(runner, "_environment_provenance", lambda _root: {})
    monkeypatch.setattr(
        runner,
        "active_strategy_families",
        lambda: frozenset({"copy_vault", "lead_lag"}),
    )
    monkeypatch.setattr(runner, "_tool", lambda name, _path: loaded_tools.append(name))

    with pytest.raises(RuntimeError, match="Copy-Vault-only active scope"):
        runner.run_campaigns(tmp_path)

    assert loaded_tools == []


def test_cli_aide_est_disponible_sans_importer_une_famille_desactivee() -> None:
    with pytest.raises(SystemExit) as exit_info:
        runner.main(["--help"])

    assert exit_info.value.code == 0

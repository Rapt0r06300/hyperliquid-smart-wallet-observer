from __future__ import annotations

import json

from hl_observer.ops import dataset_catalog, dataset_workspace


def test_dataset_catalog_parser_defaults_to_current_root():
    args = dataset_catalog._parser().parse_args([])
    assert args.root == "."
    assert args.force_metadata is False


def test_dataset_workspace_cli_calls_the_canonical_preparer(tmp_path, monkeypatch, capsys):
    materialized = tmp_path / "materialized"
    materialized.mkdir()
    calls = {}

    def fake_prepare(project_root, *, materialized_root=None):
        calls["project_root"] = project_root
        calls["materialized_root"] = materialized_root
        return {
            "schema": "test.workspace.v1",
            "project_root": str(project_root),
            "materialized_root": str(materialized_root),
        }

    monkeypatch.setattr(dataset_workspace, "prepare_replay_workspace", fake_prepare)
    rc = dataset_workspace.main(
        ["--root", str(tmp_path), "--materialized-root", str(materialized)]
    )
    assert rc == 0
    assert calls["project_root"] == tmp_path.resolve()
    assert calls["materialized_root"] == materialized.resolve()
    printed = json.loads(capsys.readouterr().out)
    assert printed["schema"] == "test.workspace.v1"

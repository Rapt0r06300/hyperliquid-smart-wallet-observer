from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from hl_observer.datasets.economic_multi_source import (
    build_copy_vault_input_view,
    install_copy_vault_adapter,
    load_cross_venue_multi_source,
    write_economic_source_coverage,
)
from hl_observer.datasets.source_discovery import load_family_source_paths


def _mark_workspace(root: Path) -> None:
    path = root / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"source_release_id": 371149058, "selection_digest": "a" * 64}),
        encoding="utf-8",
    )


def _write(root: Path, relative: str, lines: list[dict]) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in lines),
        encoding="utf-8",
    )
    return path


def _book(ts: float, *, hl_bid=100.0, hl_ask=101.0, bin_bid=100.0, bin_ask=101.0):
    return {
        "coin": "BTC",
        "collecte_ts": ts,
        "hl_bid": hl_bid,
        "hl_ask": hl_ask,
        "bin_bid": bin_bid,
        "bin_ask": bin_ask,
        "taille_min_usd": 500.0,
    }


def test_copy_view_fusionne_archives_et_rejette_lignes_exactement_dupliquees(tmp_path: Path) -> None:
    _mark_workspace(tmp_path)
    _write(
        tmp_path,
        "runtime/data/vault_fills.jsonl",
        [{"fill_id": "a", "ts_ms": 1}, {"fill_id": "b", "ts_ms": 2}],
    )
    _write(
        tmp_path,
        "archive/run1/runtime/data/vault_fills.jsonl",
        [{"fill_id": "a", "ts_ms": 1}, {"fill_id": "c", "ts_ms": 3}],
    )
    view = build_copy_vault_input_view(tmp_path)
    merged = tmp_path / str(view["outputs"]["vault_fills.jsonl"])
    rows = [json.loads(line) for line in merged.read_text(encoding="utf-8").splitlines()]
    assert {row["fill_id"] for row in rows} == {"a", "b", "c"}
    meta = view["merges"]["vault_fills.jsonl"]
    assert meta["source_count"] == 2
    assert meta["duplicate_lines_rejected"] == 1


def test_copy_adapter_ne_s_active_que_sur_workspace_dataset(tmp_path: Path) -> None:
    normal_tool = SimpleNamespace()
    normal_exec = SimpleNamespace(load_observed_books=lambda *args, **kwargs: ({}, {}))
    normal = install_copy_vault_adapter(
        tmp_path, copy_tool=normal_tool, copy_executable=normal_exec
    )
    assert normal["enabled"] is False

    _mark_workspace(tmp_path)
    _write(tmp_path, "runtime/data/vault_fills.jsonl", [{"fill_id": "a", "ts_ms": 1}])
    _write(tmp_path, "archive/runtime/data/vault_fills.jsonl", [{"fill_id": "b", "ts_ms": 2}])
    calls = []

    def fake_books(root, *, coins=None, relative_path=None, causal_relative_path=None):
        calls.append((relative_path, causal_relative_path))
        return {}, {"ok": True}

    fake_tool = SimpleNamespace()
    fake_exec = SimpleNamespace(load_observed_books=fake_books)
    result = install_copy_vault_adapter(
        tmp_path, copy_tool=fake_tool, copy_executable=fake_exec
    )
    assert result["enabled"] is True
    assert str(fake_tool.FILLS).startswith("runtime/reports/datasets/economic_inputs/")
    fake_exec.load_observed_books(tmp_path, coins={"BTC"})
    assert calls


def test_cross_multi_source_consomme_tous_les_fichiers_et_refuse_conflit(tmp_path: Path) -> None:
    _mark_workspace(tmp_path)
    _write(tmp_path, "runtime/data/carnet_venues.jsonl", [_book(1.0), _book(2.0)])
    _write(
        tmp_path,
        "archive/run1/runtime/data/carnet_venues.jsonl",
        [_book(1.0), _book(3.0)],
    )
    series, depth, meta = load_cross_venue_multi_source(tmp_path)
    assert meta["source_count"] == 2
    assert meta["duplicates_rejected"] == 1
    assert meta["conflicting_same_timestamp_rejected"] == 0
    assert len(series["BTC"]) == 3
    assert len(depth["BTC"]) == 3

    _write(
        tmp_path,
        "archive/run2/runtime/data/carnet_venues.jsonl",
        [_book(2.0, hl_bid=99.0, hl_ask=100.0)],
    )
    series2, _, meta2 = load_cross_venue_multi_source(tmp_path)
    assert meta2["source_count"] == 3
    assert meta2["conflicting_same_timestamp_rejected"] == 1
    assert len(series2["BTC"]) == 2


def test_rapport_couverture_prouve_les_sources_consommees(tmp_path: Path) -> None:
    _mark_workspace(tmp_path)
    copy = _write(tmp_path, "runtime/data/vault_fills.jsonl", [{"fill_id": "a"}])
    lead = _write(tmp_path, "runtime/data/bbo_tape.jsonl", [{"coin": "BTC"}])
    cross = _write(tmp_path, "runtime/data/carnet_venues.jsonl", [_book(1.0)])
    json_path, md_path, payload = write_economic_source_coverage(
        tmp_path,
        copy_consumed=[copy, cross],
        lead_consumed=[lead],
        cross_consumed=[cross],
    )
    assert json_path.is_file()
    assert md_path.is_file()
    assert payload["all_families_full"] is True
    assert payload["families"]["copy_vault"]["status"] == "FULL"
    assert payload["families"]["lead_lag"]["status"] == "FULL"
    assert payload["families"]["cross_venue"]["status"] == "FULL"
    assert len(load_family_source_paths(tmp_path, "cross_venue")) == 1

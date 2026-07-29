"""Bounded historical bootstrap must resume without losing any source."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import corpus_incremental as INC  # noqa: E402


def test_bootstrap_processes_every_source_once_across_bounded_cycles(
    tmp_path,
    monkeypatch,
):
    source_plan = [f"runtime/data/source-{index}.jsonl" for index in range(5)]
    calls: list[tuple[int, tuple[str, ...]]] = []
    monkeypatch.setenv("HYPERSMART_18H_MAX_SOURCES_PER_BOOTSTRAP", "2")
    monkeypatch.setenv("HYPERSMART_18H_MAX_BOOTSTRAP_MEGABYTES", "64")

    def cataloguer(
        root,
        rundir,
        *,
        source_offset=0,
        max_sources=None,
        source_paths=None,
        **kwargs,
    ):
        plan = list(source_paths) if source_paths is not None else list(source_plan)
        end = min(len(plan), source_offset + int(max_sources or len(plan)))
        selected = plan[source_offset:end]
        calls.append((source_offset, tuple(selected)))
        sources = [
            {"chemin": path, "format": "jsonl", "sha256": f"sha-{path}"}
            for path in selected
        ]
        return {
            "sources": sources,
            "source_plan": plan,
            "next_source_offset": end,
            "bootstrap_complete": end >= len(plan),
            "accounting": {
                "n_total_detected": len(plan),
                "n_batch_detected": len(selected),
                "n_catalogued": len(selected),
                "n_parsed": len(selected),
                "events": len(selected),
                "octets": len(selected),
            },
        }

    def construire(sources, *, root, max_par_source=None, **kwargs):
        assert max_par_source is None
        return {
            "episodes": [
                {
                    "coin": "BTC",
                    "ts_ms": index,
                    "bid": 99.0,
                    "ask": 101.0,
                    "source": source["chemin"],
                }
                for index, source in enumerate(sources)
            ]
        }

    run_dir = tmp_path / "run"
    first = INC.preparer_historique(
        tmp_path,
        run_dir,
        cataloguer=cataloguer,
        construire=construire,
    )
    second = INC.preparer_historique(
        tmp_path,
        run_dir,
        cataloguer=cataloguer,
        construire=construire,
    )
    third = INC.preparer_historique(
        tmp_path,
        run_dir,
        cataloguer=cataloguer,
        construire=construire,
    )
    cached = INC.preparer_historique(
        tmp_path,
        run_dir,
        cataloguer=cataloguer,
        construire=construire,
    )

    assert first["bootstrap_progress_pct"] == 40.0
    assert second["bootstrap_progress_pct"] == 80.0
    assert third["bootstrap_complete"] is True
    assert third["n_sources_deferred"] == 0
    assert cached["from_cache"] is True
    assert cached["n_sources_parsees_ce_cycle"] == 0
    assert [offset for offset, _ in calls] == [0, 2, 4]

    indexed = [
        json.loads(line)
        for line in (run_dir / "historique" / "episodes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(indexed) == len(source_plan)
    assert {row["source"] for row in indexed} == set(source_plan)
    manifest = json.loads(
        (run_dir / "historique" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["n_sources_processed"] == len(source_plan)
    assert manifest["n_sources_deferred"] == 0

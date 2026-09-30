from __future__ import annotations

import json

from hl_observer.ml import train_cli


def test_write_outputs_creates_report_and_history(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(train_cli.time, "time", lambda: 1234)
    out = str(tmp_path / "nested" / "model.json")
    report = {
        "n": 10,
        "n_win": 6,
        "saved": True,
        "evaluation": {
            "brier": 0.2,
            "baseline_brier": 0.25,
            "brier_advantage": 0.05,
            "accuracy": 0.7,
            "beats_baseline": True,
        },
    }
    train_cli._write_outputs(out, report)
    assert json.loads((tmp_path / "nested" / "model.json.report.json").read_text()) == report
    history = [json.loads(line) for line in (tmp_path / "nested" / "model.json.history.jsonl").read_text().splitlines()]
    assert history == [{
        "accuracy": 0.7,
        "baseline_brier": 0.25,
        "beats_baseline": True,
        "brier": 0.2,
        "brier_advantage": 0.05,
        "n": 10,
        "n_win": 6,
        "saved": True,
        "ts": 1234,
    }]


def test_run_ingests_samples_trains_and_normalizes_context(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.setattr(
        train_cli,
        "ingest_snapshot_to_samples",
        lambda snapshot, samples, *, context: calls.append(("ingest", snapshot, samples, context)) or 3,
    )
    monkeypatch.setattr(
        train_cli,
        "rows_outcomes_from_samples",
        lambda samples: calls.append(("samples", samples)) or ([{"x": 1}], [1]),
    )
    monkeypatch.setattr(
        train_cli,
        "train_from_dataset",
        lambda rows, outcomes, *, context, out_path, min_samples: calls.append(
            ("train", rows, outcomes, context, out_path, min_samples)
        ) or {"trained": True, "saved": True, "n": 1, "n_win": 1, "evaluation": {}},
    )
    monkeypatch.setattr(train_cli, "_write_outputs", lambda out, rep: calls.append(("write", out, dict(rep))))

    out = str(tmp_path / "model.json")
    rep = train_cli.run(
        samples="samples.jsonl",
        ingest_snapshot="snapshot.json",
        out=out,
        context="live",
        min_samples=5,
    )
    assert rep["trained"] is True
    assert rep["ingested"] == 3
    assert rep["context_requested"] == "LIVE"
    assert rep["context_effective"] == "LIVE"
    assert ("ingest", "snapshot.json", "samples.jsonl", "LIVE") in calls
    assert any(call[0] == "train" and call[3] == "LIVE" and call[5] == 5 for call in calls)
    assert any(call[0] == "write" and call[1] == out for call in calls)


def test_run_all_context_uses_unfiltered_training_and_live_ingest(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(
        train_cli,
        "ingest_snapshot_to_samples",
        lambda snapshot, samples, *, context: seen.setdefault("ingest_context", context) or 1,
    )
    monkeypatch.setattr(train_cli, "rows_outcomes_from_samples", lambda samples: ([{"x": 1}], [0]))
    monkeypatch.setattr(
        train_cli,
        "train_from_dataset",
        lambda rows, outcomes, *, context, out_path, min_samples: seen.setdefault("train_context", context) or {
            "trained": True, "saved": False, "evaluation": {}
        },
    )
    rep = train_cli.run(samples="s", ingest_snapshot="snap", context="ALL")
    assert seen["ingest_context"] == "LIVE"
    assert seen["train_context"] is None
    assert rep["context_requested"] == "ALL"
    assert rep["context_effective"] == "ALL"


def test_run_snapshot_branch_and_no_samples(monkeypatch, tmp_path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"bot_simulation": {"events": [{"id": 1}]}}), encoding="utf-8")
    monkeypatch.setattr(
        train_cli,
        "rows_outcomes_from_events",
        lambda events, *, context: ([{"event": events[0]["id"], "context": context}], [1]),
    )
    monkeypatch.setattr(
        train_cli,
        "train_from_dataset",
        lambda rows, outcomes, *, context, out_path, min_samples: {
            "trained": True, "saved": False, "rows": rows, "evaluation": {}
        },
    )
    rep = train_cli.run(snapshot=str(snapshot), context="REPLAY")
    assert rep["rows"] == [{"event": 1, "context": "REPLAY"}]
    assert rep["context_effective"] == "REPLAY"

    writes = []
    monkeypatch.setattr(train_cli, "_write_outputs", lambda out, rep: writes.append((out, dict(rep))))
    rep = train_cli.run(out="model.json", context="mixed")
    assert rep == {
        "trained": False,
        "saved": False,
        "reason": "no_samples_found",
        "n": 0,
        "ingested": 0,
        "context_requested": "MIXED",
        "context_effective": "ALL",
    }
    assert writes[0][0] == "model.json"


def test_main_parses_arguments_prints_report_and_returns_zero(monkeypatch, capsys) -> None:
    captured = {}
    monkeypatch.setattr(
        train_cli,
        "run",
        lambda **kwargs: captured.update(kwargs) or {"trained": False, "saved": False},
    )
    rc = train_cli.main([
        "--samples", "s.jsonl",
        "--snapshot", "snap.json",
        "--ingest-snapshot", "ingest.json",
        "--out", "out.json",
        "--context", "ANY",
        "--min-samples", "7",
    ])
    assert rc == 0
    assert captured == {
        "samples": "s.jsonl",
        "snapshot": "snap.json",
        "ingest_snapshot": "ingest.json",
        "out": "out.json",
        "context": "ANY",
        "min_samples": 7,
    }
    assert json.loads(capsys.readouterr().out) == {"trained": False, "saved": False}

"""Robustesse du recorder replay : par-process (sans race), capé atomiquement, lecteur agrege."""

from __future__ import annotations

from hl_observer.runtime import replay_recorder as rr


def test_per_process_write_and_read(tmp_path):
    n = rr.append_replay_lines(tmp_path, "candidates.jsonl",
                               [{"coin": "AAA", "x": 1}, {"coin": "BBB", "x": 2}],
                               max_bytes=10_000_000, max_lines=100_000)
    assert n == 2
    files = rr.iter_replay_files(tmp_path, "candidates.jsonl")
    assert len(files) >= 1
    assert all(f.name.startswith("candidates.") for f in files)  # <stem>.<pid>.jsonl
    rows = rr.read_replay_lines(tmp_path, "candidates.jsonl")
    assert len(rows) == 2
    assert {r["coin"] for r in rows} == {"AAA", "BBB"}


def test_cap_bounds_file(tmp_path):
    # petit cap => le fichier reste borne (pas de croissance infinie sur 48h)
    for _ in range(400):
        rr.append_replay_lines(tmp_path, "marks.jsonl", [{"coin": "AAA", "ts": 1.0, "mid": 1.0}],
                               max_bytes=2000, max_lines=50)
    rows = rr.read_replay_lines(tmp_path, "marks.jsonl")
    assert 1 <= len(rows) <= 80  # borne (garde une fenetre recente)


def test_merge_replay(tmp_path):
    rr.append_replay_lines(tmp_path, "candidates.jsonl", [{"coin": "AAA"}, {"coin": "CCC"}],
                           max_bytes=10_000_000, max_lines=1000)
    st = rr.merge_replay(tmp_path)
    assert st["counts"]["candidates.jsonl"] >= 2
    merged = rr.read_replay_lines(st["out"], "candidates.jsonl")
    assert len(merged) >= 2


def test_archive_accumulates_across_runs(tmp_path):
    # run precedent
    rr.append_replay_lines(tmp_path, "candidates.jsonl", [{"coin": "OLD1"}, {"coin": "OLD2"}],
                           max_bytes=10_000_000, max_lines=1000)
    st = rr.archive_previous_run(tmp_path)
    assert st["moved"] >= 1
    # top-level vide (fichiers deplaces vers _archive)
    assert rr.read_replay_lines(tmp_path, "candidates.jsonl") == []
    # include_archive retrouve les donnees du run precedent
    assert len(rr.read_replay_lines(tmp_path, "candidates.jsonl", include_archive=True)) == 2
    # nouveau run ecrit dans un runtime\replay propre
    rr.append_replay_lines(tmp_path, "candidates.jsonl", [{"coin": "NEW1"}],
                           max_bytes=10_000_000, max_lines=1000)
    # merge = ancien (archive) + nouveau => dataset qui grossit
    m = rr.merge_replay(tmp_path)
    assert m["counts"]["candidates.jsonl"] >= 3

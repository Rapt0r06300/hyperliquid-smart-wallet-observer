"""Tests de l'enregistreur de recherche : ecrit/relit, horodate, borne la taille, ne casse rien."""
from __future__ import annotations

from hl_observer.collection import research_recorder as rr


def test_record_and_read_roundtrip(tmp_path):
    base = str(tmp_path)
    for i in range(5):
        rr.record(base, "funding", {"coin": "BTC", "rate_bps_per_h": 0.1 * i})
    rows = rr.read_stream(base, "funding")
    assert len(rows) == 5
    assert all("_ts" in r for r in rows)               # horodatage ajoute
    assert rows[0]["coin"] == "BTC"


def test_streams_are_isolated(tmp_path):
    base = str(tmp_path)
    rr.record(base, "funding", {"x": 1})
    rr.record(base, "l2book", {"y": 2})
    assert len(rr.read_stream(base, "funding")) == 1
    assert len(rr.read_stream(base, "l2book")) == 1


def test_size_cap_keeps_file_bounded_and_readable(tmp_path):
    base = str(tmp_path)
    payload = {"blob": "x" * 500}
    for _ in range(400):
        rr.record(base, "latency", payload, max_bytes=20_000)
    import glob, os
    files = glob.glob(os.path.join(base, "latency.*.jsonl"))
    assert files and os.path.getsize(files[0]) <= 20_000      # borne respectee
    rows = rr.read_stream(base, "latency")
    assert rows and all("blob" in r for r in rows)            # toujours lisible/JSON valide

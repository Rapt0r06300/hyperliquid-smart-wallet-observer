from __future__ import annotations

from hl_observer.realtime.raw_spool import RawSpool


def test_relire_spool_supprime_reste_vide(tmp_path) -> None:
    path = tmp_path / "spool.jsonl"
    spool = RawSpool(path)
    spool.fermer()
    path.unlink()

    assert list(spool.relire()) == []

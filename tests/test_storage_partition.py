import pytest

from hl_observer.research.storage_partition import cle_partition_parquet, hash_partition, lineage_ligne


def test_cle_partition_parquet():
    k = cle_partition_parquet({"venue": "hl", "date": "2026-08-05", "symbole": "BTC"})
    assert k == "venue=hl/date=2026-08-05/symbole=BTC"


def test_hash_partition_detecte_alteration():
    a = hash_partition([{"px": 1}, {"px": 2}])
    assert a == hash_partition([{"px": 1}, {"px": 2}])
    assert a != hash_partition([{"px": 1}, {"px": 3}])


def test_lineage_ligne_obligatoire():
    assert lineage_ligne(42, ["hyperliquid"])["tracable"] is True
    with pytest.raises(ValueError):
        lineage_ligne(42, [])

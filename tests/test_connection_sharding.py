"""[DATA lot2 #29] connection sharding : distribue les symboles en round-robin sur N connexions."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.connection_sharding import repartir   # noqa: E402


def test_repartition_equilibree():
    r = repartir(["a", "b", "c", "d", "e"], n_shards=2)
    assert r["shards"] == [["a", "c", "e"], ["b", "d"]] and r["equilibre"] is True
    assert r["tailles"] == [3, 2]


def test_un_shard():
    r = repartir(["a", "b"], n_shards=1)
    assert r["shards"] == [["a", "b"]]


def test_n_shards_invalide():
    assert repartir(["a"], n_shards=0)["shards"] == "UNMEASURABLE"

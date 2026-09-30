"""Tests performance & scalabilité."""
from __future__ import annotations

import sqlite3

from hl_observer.backtesting.perf_tools import (
    LRUCache,
    bounded_parallel_map,
    create_sqlite_indexes,
    load_test,
    profile_call,
)


def test_lru_evicts_oldest():
    c = LRUCache(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")                 # 'a' redevient récent
    c.put("c", 3)              # évince 'b' (le plus ancien)
    assert c.get("a") == 1 and c.get("c") == 3 and c.get("b") is None
    assert len(c) == 2


def test_bounded_parallel_map():
    assert bounded_parallel_map(lambda x: x * 2, [1, 2, 3], workers=2) == [2, 4, 6]


def test_profile_call_measures():
    r = profile_call(lambda: sum(range(10000)))
    assert r["result"] == 49995000 and r["seconds"] >= 0.0 and "function calls" in r["profile"]


def test_sqlite_index_created(tmp_path):
    db = str(tmp_path / "t.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE marks (coin TEXT, ts REAL)")
    con.commit()
    con.close()
    made = create_sqlite_indexes(db, "marks", ["coin", "ts"])
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    con.close()
    assert set(made) <= names


def test_load_test_counts_errors():
    r = load_test(lambda i: 1 / (i % 5), n=20)   # échoue quand i%5==0
    assert r["runs"] == 20 and r["errors"] == 4

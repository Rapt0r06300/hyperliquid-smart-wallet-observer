"""H20 : le mid vient du meilleur bid/ask de chaque instantané ; un mid trop vieux (trou de capture) vaut NaN."""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_decroissance_tardis as D  # noqa: E402


def test_mid_par_instantane_et_trou_de_capture(tmp_path: Path) -> None:
    p = tmp_path / "BTC.csv.gz"
    lignes = ["exchange,symbol,timestamp,local_timestamp,is_snapshot,side,price,amount"]
    for ts, (b1, b2, a1) in ((1_000_000, (99.0, 98.0, 101.0)), (2_000_000, (100.0, 99.0, 102.0))):
        lignes += [f"hl,BTC,{ts},{ts},true,bid,{b1},1", f"hl,BTC,{ts},{ts},true,bid,{b2},1",
                   f"hl,BTC,{ts},{ts},true,ask,{a1},1", f"hl,BTC,{ts},{ts},true,ask,{a1 + 5},1"]
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")
    t, m = D.mids(p)
    assert list(t) == [1000, 2000] and list(m) == [100.0, 101.0]          # (99+101)/2, (100+102)/2
    got = D.mid_a(t, m, np.array([1500, 2000, 2000 + 6000]))
    assert got[0] == 100.0 and got[1] == 101.0 and np.isnan(got[2])     # 6 s apres le dernier point : NaN

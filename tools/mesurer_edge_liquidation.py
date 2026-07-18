"""Runner #3/#530 — MESURE l'edge post-liquidation sur les donnees REELLES enregistrees.

Lit les liquidations (SQLite grappe_snapshots, ecrites par le moteur) + les marks de prix (replay
recorder), puis appelle mesurer_edge_liquidation. Imprime le VERDICT honnete
(EDGE_NET_POSITIF / PAS_D_EDGE / INSUFFISANT). Aucune donnee inventee : sans assez d'evenements,
le verdict est INSUFFISANT. MESURE only, aucun ordre.

  python tools/mesurer_edge_liquidation.py [--root .] [--horizon-s 1800] [--cout-bps 12]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.backtesting.liquidation_edge_measure import mesurer_edge_liquidation  # noqa: E402
from hl_observer.market.liquidation_recorder import _db_path  # noqa: E402
from hl_observer.runtime.replay_recorder import read_replay_lines  # noqa: E402


def _lire_liquidations(root: str) -> list[dict]:
    path = _db_path(root)
    if not Path(path).exists():
        return []
    con = sqlite3.connect(str(path))
    try:
        cur = con.execute("SELECT coin, ts_ms, prix, sens FROM grappe_snapshots ORDER BY ts_ms")
        return [{"coin": c, "ts_ms": t, "prix": p, "sens": s} for (c, t, p, s) in cur.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _lire_marks(root: str) -> dict[str, list]:
    base = Path(root) / "runtime" / "replay"
    out: dict[str, list] = {}
    for r in read_replay_lines(base, "marks.jsonl", include_archive=True):
        try:
            coin = str(r.get("coin") or "").upper()
            ts, mid = float(r.get("ts")), float(r.get("mid"))
        except (TypeError, ValueError):
            continue
        if coin and mid > 0:
            out.setdefault(coin, []).append((ts, mid))
    for c in out:
        out[c].sort()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mesure d'edge post-liquidation (read-only)")
    ap.add_argument("--root", default=".")
    ap.add_argument("--horizon-s", type=float, default=1800.0)
    ap.add_argument("--cout-bps", type=float, default=12.0)
    a = ap.parse_args(argv)
    evs = _lire_liquidations(a.root)
    marks = _lire_marks(a.root)
    rap = mesurer_edge_liquidation(evs, marks, horizon_s=a.horizon_s, cout_aller_retour_bps=a.cout_bps)
    print(json.dumps(rap.as_dict(), ensure_ascii=False, indent=2))
    if rap.verdict == "INSUFFISANT":
        print("\n>>> INSUFFISANT : laisse le moteur tourner plus longtemps pour accumuler des "
              "liquidations (voir docs/RUNBOOK_COLLECTE_DONNEES.md). On ne conclut pas sur du vide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

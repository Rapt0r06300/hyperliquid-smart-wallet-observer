"""Materialisation de l'espace de scenarios dans une base SQLite (pour le replay futur).

Construit une DB `scenarios.db` contenant >= N scenarios DISTINCTS (defaut 300 000) couvrant
le MAXIMUM de parametres (15 dimensions : filtres d'entree mappes aux champs reels des
candidats + politique de sortie + cout). Reutilise le `Scenario` de `scenario_grid.py`
(source unique, PAS de duplication d'espace).

Chargement de `scenario_grid.py` PAR FICHIER (importlib) : quand ce module est lance en
script direct, il n'importe PAS le package `hl_observer` (aucun effet de bord, ne touche ni
aux logs ni au logiciel en cours). `scenario_grid.py` n'importe que la stdlib.

Pur / deterministe (seed) / read-only vis-a-vis du runtime : n'ecrit QUE le fichier DB cible.

Usage (build reel) :
    python src/hl_observer/backtesting/scenario_db.py --count 300000 \
        --out runtime/scenarios/scenarios.db --seed 7
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

# --- Chargement de scenario_grid.py PAR FICHIER (pas d'import du package runtime) ---
# On enregistre le module dans sys.modules AVANT exec_module : requis par @dataclass
# (Python 3.12+ fait sys.modules.get(cls.__module__) lors du traitement de la classe).
_GRID_PATH = Path(__file__).resolve().with_name("scenario_grid.py")
_spec = importlib.util.spec_from_file_location("_scenario_grid_standalone", _GRID_PATH)
_sg = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _sg
_spec.loader.exec_module(_sg)  # type: ignore[union-attr]

generate_many = _sg.generate_many
SCENARIO_FIELDS = list(_sg.SCENARIO_FIELDS)

GENERATOR_VERSION = "scenario_db/v2-stream"
_TEXT_FIELDS = {"name", "source", "side_mode"}
_INT_FIELDS = {"min_consensus_wallets"}


def _sqlite_type(field: str) -> str:
    if field in _TEXT_FIELDS:
        return "TEXT"
    if field in _INT_FIELDS:
        return "INTEGER"
    return "REAL"


def _param_hash(sc) -> str:
    return hashlib.sha1(repr(sc.key()).encode("utf-8")).hexdigest()


def _create_schema(con: sqlite3.Connection) -> None:
    cols = ['id INTEGER PRIMARY KEY AUTOINCREMENT', 'param_hash TEXT UNIQUE']
    cols += [f'"{f}" {_sqlite_type(f)}' for f in SCENARIO_FIELDS]
    con.execute("DROP TABLE IF EXISTS scenarios")
    con.execute(f"CREATE TABLE scenarios ({', '.join(cols)})")
    con.execute("DROP TABLE IF EXISTS meta")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")


def _row_of(sc) -> tuple:
    return tuple([_param_hash(sc)] + [getattr(sc, f) for f in SCENARIO_FIELDS])


def build_database(out_path: str | Path, count: int = 300000, *, seed: int = 7,
                   batch_rows: int = 50000) -> dict:
    """Ecrit EXACTEMENT `count` scenarios distincts dans une DB SQLite (streaming, memoire bornee).

    Socle deterministe (archetypes + grid) puis flot aleatoire ; dedup au niveau DB via
    param_hash UNIQUE (pas de gros set en memoire). Repart d'une DB propre. Deterministe (seed).
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()  # rebuild propre

    insert_cols = ["param_hash"] + [f'"{f}"' for f in SCENARIO_FIELDS]
    placeholders = ", ".join(["?"] * len(insert_cols))
    sql = f"INSERT OR IGNORE INTO scenarios ({', '.join(insert_cols)}) VALUES ({placeholders})"
    target = int(count)

    con = sqlite3.connect(str(out))
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA temp_store=MEMORY")
        _create_schema(con)

        # 1) socle deterministe : archetypes + grid (toujours inclus, ids les plus bas)
        socle = _sg.archetype_scenarios() + _sg.grid_scenarios()
        con.executemany(sql, [_row_of(s) for s in socle])
        con.commit()

        # 2) flot aleatoire jusqu'a `target` (dedup DB) ; memoire = 1 batch a la fois
        rng = random.Random(int(seed))
        idx = 0
        n = con.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
        while n < target:
            need = min(int(batch_rows), (target - n) * 2 + 1000)
            batch = [_row_of(_sg._sample_one(rng, idx + j)) for j in range(need)]
            idx += need
            con.executemany(sql, batch)
            con.commit()
            n = con.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]

        # 3) coupe a EXACTEMENT target (garde les plus petits id => socle conserve)
        thr = con.execute("SELECT id FROM scenarios ORDER BY id LIMIT 1 OFFSET ?",
                          (target - 1,)).fetchone()
        if thr is not None:
            con.execute("DELETE FROM scenarios WHERE id > ?", (thr[0],))
        con.execute("CREATE INDEX IF NOT EXISTS idx_scenarios_source ON scenarios(source)")
        con.commit()

        rows = con.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
        by_source = dict(con.execute(
            "SELECT source, COUNT(*) FROM scenarios GROUP BY source").fetchall())
        meta = {
            "generator_version": GENERATOR_VERSION,
            "seed": int(seed),
            "count_requested": target,
            "count_rows": int(rows),
            "dimensions": SCENARIO_FIELDS,
            "by_source": by_source,
            "created_at_ms": int(time.time() * 1000),
            "note": "REPLAY-only. Metriques descriptives. Aucun ordre reel.",
        }
        con.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()

    meta["bytes"] = out.stat().st_size if out.exists() else 0
    meta["path"] = str(out)
    return meta


# ---------------------------------------------------------------------------
# Construction A GRANDE ECHELLE (dizaines / centaines de millions).
# Schema compact append-only, SANS index/hash unique : a cette echelle les
# doublons sont statistiquement negligeables (espace > 1e20 combinaisons), et
# l'index unique deviendrait le goulot (taille + insertions). Beaucoup plus
# rapide/compact. Deterministe (seed). REPLAY-only, aucun ordre reel.
# ---------------------------------------------------------------------------

_DIM_COLS = list(_sg.DIM_ORDER)
_SRC_CODE = {"archetype": 0, "grid": 1, "sampled_full": 2}
_SRC_NAME = {0: "archetype", 1: "grid", 2: "sampled_full"}


def _scale_schema(con: sqlite3.Connection) -> None:
    cols = ["id INTEGER PRIMARY KEY", '"source" INTEGER']
    cols += [f'"{f}" {_sqlite_type(f)}' for f in _DIM_COLS]
    con.execute("DROP TABLE IF EXISTS scenarios")
    con.execute(f"CREATE TABLE scenarios ({', '.join(cols)})")
    con.execute("DROP TABLE IF EXISTS meta")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")


def build_database_scale(out_path: str | Path, count: int, *, seed: int = 7,
                         batch_rows: int = 200000) -> dict:
    """Ecrit `count` scenarios en append-only (rapide, compact). Deterministe (seed)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    target = int(count)
    ncols = 1 + len(_DIM_COLS)
    col_sql = ", ".join(['"source"'] + [f'"{f}"' for f in _DIM_COLS])
    sql = f"INSERT INTO scenarios ({col_sql}) VALUES ({', '.join(['?'] * ncols)})"

    con = sqlite3.connect(str(out))
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA temp_store=MEMORY")
        con.execute("PRAGMA cache_size=-200000")  # ~200 Mo
        _scale_schema(con)

        socle = (_sg.archetype_scenarios() + _sg.grid_scenarios())[:target]
        con.executemany(sql, [tuple([_SRC_CODE.get(s.source, 9)]
                                    + [getattr(s, f) for f in _DIM_COLS]) for s in socle])
        written = len(socle)
        con.commit()

        rng = random.Random(int(seed))
        while written < target:
            need = min(int(batch_rows), target - written)
            con.executemany(sql, [(2,) + _sg.sample_row(rng) for _ in range(need)])
            written += need
            con.commit()

        rows = con.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
        by_source = {_SRC_NAME.get(k, str(k)): v for k, v in
                     con.execute("SELECT source, COUNT(*) FROM scenarios GROUP BY source").fetchall()}
        meta = {
            "generator_version": "scenario_db/v3-scale",
            "seed": int(seed),
            "count_requested": target,
            "count_rows": int(rows),
            "schema": "compact_append_only_no_hash",
            "dimensions": _DIM_COLS,
            "by_source": by_source,
            "note": "REPLAY-only. Doublons negligeables (pas d'index unique). Aucun ordre reel.",
            "created_at_ms": int(time.time() * 1000),
        }
        con.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
        con.commit()
    finally:
        con.close()
    meta["bytes"] = out.stat().st_size if out.exists() else 0
    meta["path"] = str(out)
    return meta


def iter_db_scenarios(path: str | Path, *, limit: int | None = None, start_id: int = 0):
    """Reconstruit des `Scenario` depuis une DB (schema scale OU standard) pour le replay.

    Utilise la classe CANONIQUE hl_observer.backtesting.scenario_grid.Scenario (importable dans
    les process workers => picklable en multiprocessing). Repli sur la copie file-load si le
    package n'est pas importable (build direct isole).
    """
    try:
        from hl_observer.backtesting.scenario_grid import Scenario
    except Exception:
        Scenario = _sg.Scenario
    con = sqlite3.connect(str(path))
    try:
        present = [r[1] for r in con.execute("PRAGMA table_info(scenarios)")]
        dim_cols = [c for c in _DIM_COLS if c in present]
        has_source = "source" in present
        sel = (["source"] if has_source else []) + dim_cols
        q = f"SELECT {', '.join(sel)} FROM scenarios"
        params: list = []
        if start_id:  # reprendre APRES ce qu'un run precedent a deja couvert (id > start_id)
            q += " WHERE id > ?"
            params.append(int(start_id))
        if limit:
            q += f" LIMIT {int(limit)}"
        for row in con.execute(q, params):
            base = 1 if has_source else 0
            src = row[0] if has_source else 2
            kw = {c: row[base + j] for j, c in enumerate(dim_cols)}
            src_name = _SRC_NAME.get(src, str(src)) if isinstance(src, int) else str(src)
            yield Scenario(name="db", source=src_name, **kw)
    finally:
        con.close()


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Construit la DB SQLite de scenarios (replay).")
    ap.add_argument("--count", type=int, default=300000)
    ap.add_argument("--out", default="runtime/scenarios/scenarios.db")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--scale", action="store_true",
                    help="Build append-only grande echelle (dizaines/centaines de millions)")
    ap.add_argument("--batch-rows", type=int, default=200000)
    args = ap.parse_args(argv)
    if args.scale:
        stats = build_database_scale(args.out, args.count, seed=args.seed, batch_rows=args.batch_rows)
    else:
        stats = build_database(args.out, count=args.count, seed=args.seed)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

"""X-11 (#372) — L'ENREGISTREUR de la carte des liquidations. Le chaînon qui manquait.

`market/liquidation_map.py` (l'instrument) disait lui-même : « l'instrument existe, la mesure
PAS — on n'a jamais enregistré `liquidationPx`, donc aucun historique ». L'observer construisait
la carte À CHAQUE observation… et la jetait. Une capacité présente, un chaînon manquant,
personne qui se plaint.

Ce module écrit chaque snapshot de grappes dans une base SQLite DÉDIÉE
(`runtime/data/liquidation_map.sqlite3` — séparée de la base principale : le bloat SQLite a
déjà fait crasher un run de 48 h). C'est cette table que `backtesting/liquidation_cascade.py`
(markout sur MID, ≥ 20 événements, un négatif TUE la piste) consommera quand l'historique
existera. Les 4 pièges de la piste restent affichés dans la doc de mesure — rien n'est promis.

⚠️ La carte est BORGNE par construction : on ne voit `liquidationPx` que des wallets suivis.
C'est une borne basse, jamais une image fidèle. La table enregistre ce qu'on VOIT, rien d'autre.

Read-only / paper-only : on ÉCRIT une observation, on ne passe aucun ordre.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

DB_RELPATH = Path("runtime") / "data" / "liquidation_map.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS grappe_snapshots (
    id INTEGER PRIMARY KEY,
    ts_ms INTEGER NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    coin TEXT NOT NULL,
    prix REAL NOT NULL,
    sens TEXT NOT NULL,
    notionnel_usd REAL NOT NULL,
    n_wallets INTEGER NOT NULL,
    distance_bps REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_grappe_coin_ts ON grappe_snapshots(coin, ts_ms);
CREATE INDEX IF NOT EXISTS ix_grappe_ts ON grappe_snapshots(ts_ms);
"""


def _db_path(root: str | Path = ".") -> Path:
    return Path(root) / DB_RELPATH


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_SCHEMA)
    return con


def rows_depuis_grappes(grappes: Iterable[Any], *, ts_ms: int, session_id: str) -> list[tuple]:
    """PUR. Accepte les objets `Grappe` (attributs) ou leurs dicts (`as_dict`). Une grappe
    illisible est ÉCARTÉE — on n'enregistre jamais une valeur devinée."""
    rows: list[tuple] = []
    for g in grappes:
        src: Mapping[str, Any]
        if isinstance(g, Mapping):
            src = g
        else:
            src = {k: getattr(g, k, None) for k in ("coin", "prix", "sens", "notionnel_usd", "n_wallets", "distance_bps")}
        try:
            coin = str(src.get("coin") or "").upper()
            prix = float(src["prix"])
            sens = str(src.get("sens") or "")
            notionnel = float(src["notionnel_usd"])
            n_wallets = int(src["n_wallets"])
            distance = float(src["distance_bps"])
        except (KeyError, TypeError, ValueError):
            continue
        if not coin or sens not in ("SELL", "BUY") or prix <= 0:
            continue
        rows.append((int(ts_ms), str(session_id or ""), coin, prix, sens, notionnel, n_wallets, distance))
    return rows


def enregistrer_grappes(grappes: Iterable[Any], *, root: str | Path = ".",
                        ts_ms: int | None = None, session_id: str = "",
                        db_path: str | Path | None = None) -> int:
    """Écrit un snapshot. Retourne le nombre de lignes écrites (0 = rien à cartographier)."""
    rows = rows_depuis_grappes(grappes, ts_ms=int(ts_ms or time.time() * 1000), session_id=session_id)
    if not rows:
        return 0
    path = Path(db_path) if db_path else _db_path(root)
    con = _connect(path)
    try:
        with con:
            con.executemany(
                "INSERT INTO grappe_snapshots(ts_ms, session_id, coin, prix, sens, notionnel_usd, n_wallets, distance_bps)"
                " VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)
    finally:
        con.close()


def resume_historique(*, root: str | Path = ".", db_path: str | Path | None = None) -> dict[str, Any]:
    """LE LECTEUR du recorder : combien d'histoire a-t-on VRAIMENT ? (Sans historique,
    la mesure `liquidation_cascade` est impossible — et on le DIT au lieu de l'inventer.)"""
    path = Path(db_path) if db_path else _db_path(root)
    if not path.exists():
        return {"snapshots": 0, "coins": 0, "premier_ts_ms": None, "dernier_ts_ms": None,
                "heures_couvertes": 0.0, "verdict": "AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE"}
    con = _connect(path)
    try:
        n, coins, tmin, tmax = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT coin), MIN(ts_ms), MAX(ts_ms) FROM grappe_snapshots"
        ).fetchone()
        heures = round(((tmax or 0) - (tmin or 0)) / 3_600_000.0, 2) if n else 0.0
        return {
            "snapshots": int(n or 0), "coins": int(coins or 0),
            "premier_ts_ms": tmin, "dernier_ts_ms": tmax, "heures_couvertes": heures,
            "verdict": ("HISTORIQUE_EN_CONSTITUTION" if n else "AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE"),
            "real_execution": False,
        }
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    import argparse, json as _json
    p = argparse.ArgumentParser(description="Historique de la carte des liquidations (X-11, read-only)")
    p.add_argument("--root", default=".")
    p.add_argument("--report", action="store_true")
    args = p.parse_args(argv)
    print(_json.dumps(resume_historique(root=args.root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

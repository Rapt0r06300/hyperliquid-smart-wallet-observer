"""V13 #163 — Recherche locale du ledger (SQLite FTS5, GRATUIT) — alt légère à LanceDB.

Indexe le texte des décisions/refus et permet une recherche plein-texte locale ("pourquoi
BTC refusé", "stale", etc.). FTS5 est inclus dans CPython ; repli LIKE si indisponible.
Pur / local / lecture seule : aucune donnée externe, aucun ordre.
"""

from __future__ import annotations

import sqlite3


class LedgerSearch:
    def __init__(self, db_path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(db_path)
        self.fts = self._supports_fts5()
        if self.fts:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS ledger_fts "
                "USING fts5(decision_id, coin, reason, text)")
        else:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS ledger_fts "
                "(decision_id TEXT, coin TEXT, reason TEXT, text TEXT)")
        self.conn.commit()

    def _supports_fts5(self) -> bool:
        try:
            self.conn.execute("CREATE VIRTUAL TABLE __fts5_probe USING fts5(x)")
            self.conn.execute("DROP TABLE __fts5_probe")
            return True
        except sqlite3.OperationalError:
            return False

    def index(self, rows: list[dict]) -> int:
        n = 0
        for r in rows or []:
            self.conn.execute(
                "INSERT INTO ledger_fts (decision_id, coin, reason, text) VALUES (?,?,?,?)",
                (str(r.get("decision_id", "")), str(r.get("coin", "")),
                 str(r.get("reason", "")), str(r.get("text", ""))))
            n += 1
        self.conn.commit()
        return n

    def search(self, query: str, *, limit: int = 20) -> list[dict]:
        q = str(query or "").strip()
        if not q:
            return []
        cur = self.conn.cursor()
        try:
            if self.fts:
                cur.execute("SELECT decision_id, coin, reason, text FROM ledger_fts "
                            "WHERE ledger_fts MATCH ? LIMIT ?", (q, int(limit)))
            else:
                like = f"%{q}%"
                cur.execute("SELECT decision_id, coin, reason, text FROM ledger_fts "
                            "WHERE text LIKE ? OR reason LIKE ? OR coin LIKE ? LIMIT ?",
                            (like, like, like, int(limit)))
        except sqlite3.OperationalError:
            like = f"%{q}%"
            cur.execute("SELECT decision_id, coin, reason, text FROM ledger_fts "
                        "WHERE text LIKE ? LIMIT ?", (like, int(limit)))
        return [{"decision_id": a, "coin": b, "reason": c, "text": d} for (a, b, c, d) in cur.fetchall()]

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM ledger_fts").fetchone()[0])


__all__ = ["LedgerSearch"]

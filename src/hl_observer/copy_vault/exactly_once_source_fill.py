"""[COPY-VAULT #60] EXACTLY-ONCE SOURCE FILL : chaque fill source est identifié de façon unique par
(wallet + tid/hash + oid), de sorte qu'un même fill ne soit consommé qu'UNE fois — même s'il arrive deux fois
(rejeu WS, double flux). C'est l'index d'unicité qui garantit l'exactly-once côté ingestion. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def identite(*, wallet: str, tid: Any = None, oid: Any = None, hash_: Any = None) -> str:
    """Clé d'identité d'un fill. Au moins un discriminant (tid/oid/hash) requis en plus du wallet."""
    # Keep the field name and the value length in the key.  Joining values only
    # made ``tid=1`` collide with ``oid=1`` and allowed delimiter-containing
    # values to produce ambiguous identities.
    parts = []
    for name, value in (("tid", tid), ("oid", oid), ("hash", hash_)):
        if value is None:
            continue
        text = str(value)
        parts.append(f"{name}:{len(text)}:{text}")
    return "%s#%s" % (str(wallet).lower(), "|".join(parts))


class RegistreFills:
    """Ensemble des identités de fills déjà consommées. `consommer` est idempotent (2e fois → deja_vu)."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._vus: set[str] = set()
        self._storage_error: str | None = None
        self._connection: sqlite3.Connection | None = None
        if storage_path is not None:
            try:
                path = Path(storage_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(str(path), timeout=5.0)
                self._connection.execute("PRAGMA busy_timeout = 5000")
                self._connection.execute("PRAGMA synchronous = FULL")
                self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS fills_seen ("
                    "identity TEXT PRIMARY KEY NOT NULL)"
                )
                self._connection.commit()
            except (OSError, sqlite3.Error) as exc:
                self._storage_error = type(exc).__name__
                if self._connection is not None:
                    self._connection.close()
                self._connection = None

    def deja_vu(self, cle: str) -> bool:
        key = str(cle)
        if self._connection is None:
            return key in self._vus
        try:
            row = self._connection.execute(
                "SELECT 1 FROM fills_seen WHERE identity = ?", (key,)
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def consommer(self, *, wallet: str, tid: Any = None, oid: Any = None, hash_: Any = None) -> dict[str, Any]:
        """Marque le fill consommé. Refuse (nouveau=False) si l'identité a déjà été vue. Aucun discriminant →
        refus (on ne consomme jamais un fill non identifiable, il pourrait être un doublon)."""
        if tid is None and oid is None and hash_ is None:
            return {"nouveau": False, "raison": "FILL_NON_IDENTIFIABLE"}
        cle = identite(wallet=wallet, tid=tid, oid=oid, hash_=hash_)
        if self._storage_error is not None:
            return {
                "nouveau": False,
                "cle": cle,
                "raison": "REGISTRE_DURABILITE_INDISPONIBLE",
            }
        if self._connection is not None:
            try:
                cursor = self._connection.execute(
                    "INSERT OR IGNORE INTO fills_seen(identity) VALUES (?)", (cle,)
                )
                self._connection.commit()
                if cursor.rowcount != 1:
                    return {"nouveau": False, "cle": cle, "raison": "DEJA_CONSOMME"}
                return {"nouveau": True, "cle": cle, "raison": "OK"}
            except sqlite3.Error as exc:
                self._storage_error = type(exc).__name__
                return {
                    "nouveau": False,
                    "cle": cle,
                    "raison": "REGISTRE_DURABILITE_INDISPONIBLE",
                }
        if cle in self._vus:
            return {"nouveau": False, "cle": cle, "raison": "DEJA_CONSOMME"}
        self._vus.add(cle)
        return {"nouveau": True, "cle": cle, "raison": "OK"}

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "RegistreFills":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


__all__ = ["identite", "RegistreFills"]

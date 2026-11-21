"""IA-7/8 — Mémoire IA incassable (SQLite WAL) + checkpoints versionnés.

Demande de Flo: l'IA doit apprendre sans JAMAIS perdre la mémoire, même serveur
fermé. Store SQLite en mode WAL (résiste aux arrêts brutaux), sous runtime/ (jamais
purgé par les resets de logs). Échantillons + prédictions vs réel + checkpoints de
modèle versionnés. Apprentissage incrémental: un nouveau checkpoint ne devient
"actif" que s'il bat le précédent en validation (best_only). Survit à tout restart.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = "runtime/ml/ia_memory.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    decision_id TEXT PRIMARY KEY, ts_ms INTEGER, context TEXT,
    features_json TEXT, net_pnl_usdc REAL, created_ms INTEGER
);
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT, ts_ms INTEGER,
    predicted REAL, realized REAL, created_ms INTEGER
);
CREATE TABLE IF NOT EXISTS checkpoints (
    version INTEGER PRIMARY KEY, created_ms INTEGER, metric REAL,
    is_active INTEGER, model_json TEXT
);
"""


class IAMemory:
    def __init__(self, path: str = DEFAULT_DB) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Ouvre, valide ou annule, puis FERME -- les trois, a chaque operation.
        # CORRECTIF DU 21/11/2026 -- `with sqlite3.connect(p) as c:` VALIDE la
        # transaction mais ne FERME JAMAIS la connexion (prouve sur Python 3.14.2 /
        # sqlite 3.50.4). Cette fabrique etait appelee a CHAQUE operation et son
        # resultat consomme par `with ...`, donc une connexion fuyait par operation :
        # sous Windows le fichier reste verrouille et, en WAL, chaque connexion
        # survivante retient le journal. `closing()` ferme mais ne valide pas : il faut
        # donc LES DEUX. La forme retenue garde `with connection:` AUTOUR du yield, ce
        # qui preserve exactement le commit/rollback que le site d appel fournissait
        # avant -- seule la fermeture est ajoutee.
        """
        c = sqlite3.connect(self.path, timeout=10)
        try:
            c.execute("PRAGMA journal_mode=WAL")       # résiste aux arrêts brutaux
            c.execute("PRAGMA synchronous=NORMAL")
            with c:
                yield c
        finally:
            c.close()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    # --- échantillons (dédupliqués par decision_id) ---
    def add_sample(self, decision_id: str, ts_ms: int, context: str, features: dict, net_pnl_usdc: float) -> bool:
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT OR IGNORE INTO samples VALUES (?,?,?,?,?,?)",
                    (str(decision_id), int(ts_ms), str(context), json.dumps(features, sort_keys=True),
                     float(net_pnl_usdc), int(time.time() * 1000)),
                )
                return c.total_changes > 0
        except sqlite3.Error:
            return False

    def sample_count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM samples").fetchone()[0])

    def record_prediction(self, decision_id: str, ts_ms: int, predicted: float, realized: float | None) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO predictions (decision_id, ts_ms, predicted, realized, created_ms) VALUES (?,?,?,?,?)",
                      (str(decision_id), int(ts_ms), float(predicted),
                       None if realized is None else float(realized), int(time.time() * 1000)))

    # --- checkpoints versionnés, promotion best-only ---
    def save_checkpoint(self, model: dict, metric: float) -> dict:
        """Enregistre un checkpoint; l'active seulement s'il bat le meilleur métrique."""
        with self._conn() as c:
            row = c.execute("SELECT MAX(version), MAX(metric) FROM checkpoints").fetchone()
            next_ver = int((row[0] or 0)) + 1
            best_metric = row[1]
            promote = best_metric is None or float(metric) > float(best_metric)
            if promote:
                c.execute("UPDATE checkpoints SET is_active=0")
            c.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?)",
                      (next_ver, int(time.time() * 1000), float(metric), 1 if promote else 0,
                       json.dumps(model, sort_keys=True)))
            return {"version": next_ver, "promoted": promote, "metric": float(metric),
                    "beat": None if best_metric is None else float(best_metric)}

    def active_checkpoint(self) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT version, metric, model_json FROM checkpoints WHERE is_active=1 ORDER BY version DESC LIMIT 1").fetchone()
            if not r:
                return None
            return {"version": int(r[0]), "metric": float(r[1]), "model": json.loads(r[2])}

    def checkpoint_count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0])


__all__ = ["DEFAULT_DB", "IAMemory"]

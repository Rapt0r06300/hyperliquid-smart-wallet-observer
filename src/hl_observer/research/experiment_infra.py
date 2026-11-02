"""[AUD-162/164/165/166/178] Infrastructure d'experiences : registre SQLite PERSISTANT des essais,
recalcul DESCENDANT cible (invalidation transitive), map DETERMINISTE parallele (ordre d'entree
preserve), reduction HORS-MEMOIRE par morceaux (larger-than-RAM), et cache par NOEUD de DAG
(adressage par contenu). stdlib pure (sqlite3, threading, hashlib), 0 reseau, 0 ordre reel."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


def _canonical_json(value: Mapping, field_name: str) -> str:
    """Encode a JSON object canonically, refusing non-reproducible values."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain finite JSON values") from exc


def _payload_digest(params_json: str, metriques_json: str) -> str:
    payload = f"params\x00{params_json}\x00metriques\x00{metriques_json}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class RegistreExperiencesSQLite:
    """Registre PERSISTANT des essais (params -> metriques) dans SQLite. Survit au redemarrage :
    rouvrir le meme fichier retrouve tous les essais. La table `essais` expose le dernier état
    pour compatibilité, tandis que `essais_historique` conserve chaque version distincte et son
    hash canonique. Une réécriture silencieuse est donc détectable et non destructive."""

    def __init__(self, chemin: str | Path) -> None:
        self.chemin = str(chemin)
        self._cx = sqlite3.connect(self.chemin)
        self._cx.execute(
            "CREATE TABLE IF NOT EXISTS essais "
            "(trial_id TEXT PRIMARY KEY, params TEXT, metriques TEXT, "
            "version INTEGER NOT NULL DEFAULT 1, payload_sha256 TEXT, updated_at_utc TEXT)")
        columns = {
            row[1] for row in self._cx.execute("PRAGMA table_info(essais)").fetchall()
        }
        for name, declaration in (
            ("version", "INTEGER NOT NULL DEFAULT 1"),
            ("payload_sha256", "TEXT"),
            ("updated_at_utc", "TEXT"),
        ):
            if name not in columns:
                self._cx.execute(f"ALTER TABLE essais ADD COLUMN {name} {declaration}")
        self._cx.execute(
            "CREATE TABLE IF NOT EXISTS essais_historique ("
            "trial_id TEXT NOT NULL, version INTEGER NOT NULL, params TEXT NOT NULL, "
            "metriques TEXT NOT NULL, payload_sha256 TEXT NOT NULL, recorded_at_utc TEXT NOT NULL, "
            "PRIMARY KEY (trial_id, version), UNIQUE (trial_id, payload_sha256))"
        )
        self._cx.commit()

    def enregistrer(self, trial_id: str, params: Mapping, metriques: Mapping) -> dict:
        """Persist a distinct version and return its durable receipt.

        Replaying byte-identical inputs is idempotent and creates no duplicate history row.
        A changed result updates the compatibility view and appends one immutable history row.
        """
        trial = str(trial_id).strip()
        if not trial:
            raise ValueError("trial_id must be non-empty")
        params_json = _canonical_json(params, "params")
        metriques_json = _canonical_json(metriques, "metriques")
        digest = _payload_digest(params_json, metriques_json)
        recorded_at = _utc_now()
        self._cx.execute("BEGIN IMMEDIATE")
        try:
            existing = self._cx.execute(
                "SELECT version, payload_sha256 FROM essais WHERE trial_id=?", (trial,)
            ).fetchone()
            if existing is not None and existing[1] == digest:
                self._cx.commit()
                return {
                    "trial_id": trial,
                    "version": int(existing[0]),
                    "payload_sha256": digest,
                    "deduplicated": True,
                }
            version = int(existing[0]) + 1 if existing is not None else 1
            self._cx.execute(
                "INSERT INTO essais_historique VALUES (?,?,?,?,?,?)",
                (trial, version, params_json, metriques_json, digest, recorded_at),
            )
            self._cx.execute(
                "INSERT INTO essais (trial_id, params, metriques, version, payload_sha256, updated_at_utc) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(trial_id) DO UPDATE SET "
                "params=excluded.params, metriques=excluded.metriques, version=excluded.version, "
                "payload_sha256=excluded.payload_sha256, updated_at_utc=excluded.updated_at_utc",
                (trial, params_json, metriques_json, version, digest, recorded_at),
            )
            self._cx.commit()
        except Exception:
            self._cx.rollback()
            raise
        return {
            "trial_id": trial,
            "version": version,
            "payload_sha256": digest,
            "deduplicated": False,
        }

    def lire(self, trial_id: str) -> dict | None:
        row = self._cx.execute(
            "SELECT params, metriques, version, payload_sha256, updated_at_utc "
            "FROM essais WHERE trial_id=?", (str(trial_id),)).fetchone()
        if row is None:
            return None
        return {
            "trial_id": str(trial_id),
            "params": json.loads(row[0]),
            "metriques": json.loads(row[1]),
            "version": int(row[2]),
            "payload_sha256": row[3],
            "updated_at_utc": row[4],
        }

    def historique(self, trial_id: str) -> list[dict]:
        """Return all immutable versions in ascending order."""
        rows = self._cx.execute(
            "SELECT trial_id, version, params, metriques, payload_sha256, recorded_at_utc "
            "FROM essais_historique WHERE trial_id=? ORDER BY version", (str(trial_id),)
        ).fetchall()
        return [
            {
                "trial_id": row[0],
                "version": int(row[1]),
                "params": json.loads(row[2]),
                "metriques": json.loads(row[3]),
                "payload_sha256": row[4],
                "recorded_at_utc": row[5],
            }
            for row in rows
        ]

    def verifier_integrite(self, trial_id: str | None = None) -> dict:
        """Verify hashes, contiguous versions and latest-view reconciliation."""
        trials = [str(trial_id)] if trial_id is not None else [
            row[0] for row in self._cx.execute("SELECT trial_id FROM essais ORDER BY trial_id")
        ]
        problems: list[str] = []
        checked = 0
        for trial in trials:
            current = self.lire(trial)
            history = self.historique(trial)
            if current is None:
                problems.append(f"{trial}:current_missing")
                continue
            if not history:
                problems.append(f"{trial}:history_missing")
                continue
            expected_versions = list(range(1, len(history) + 1))
            actual_versions = [row["version"] for row in history]
            if actual_versions != expected_versions:
                problems.append(f"{trial}:versions_not_contiguous")
            for row in history:
                digest = _payload_digest(
                    _canonical_json(row["params"], "params"),
                    _canonical_json(row["metriques"], "metriques"),
                )
                if digest != row["payload_sha256"]:
                    problems.append(f"{trial}:history_hash_mismatch_v{row['version']}")
            latest = history[-1]
            if (
                current["version"] != latest["version"]
                or current["payload_sha256"] != latest["payload_sha256"]
            ):
                problems.append(f"{trial}:latest_view_mismatch")
            checked += 1
        return {"ok": not problems, "checked": checked, "problems": problems}

    def compter(self) -> int:
        return int(self._cx.execute("SELECT COUNT(*) FROM essais").fetchone()[0])

    def fermer(self) -> None:
        self._cx.close()

    def __enter__(self) -> "RegistreExperiencesSQLite":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.fermer()


def recompute_descendant(dependances: Mapping[str, Sequence[str]], noeud_change: str) -> list[str]:
    """Recalcul CIBLE : graphe {noeud: [dependances amont]}. Retourne les noeuds DESCENDANTS
    (transitifs) a recalculer quand `noeud_change` change -> on ne recalcule QUE l'aval touche."""
    avals: dict[str, list[str]] = {}
    for noeud, amonts in dependances.items():
        for a in amonts:
            avals.setdefault(a, []).append(noeud)
    a_recalculer: list[str] = []
    vus = set()
    pile = [noeud_change]
    while pile:
        cur = pile.pop()
        for suivant in avals.get(cur, []):
            if suivant not in vus:
                vus.add(suivant)
                a_recalculer.append(suivant)
                pile.append(suivant)
    return a_recalculer


def map_deterministe(fn: Callable, items: Sequence, *, workers: int = 4) -> list:
    """Parallelisme DETERMINISTE : fn en parallele mais RESULTATS dans l'ordre d'ENTREE (independant
    de l'ordre de fin). Meme entree -> meme sortie, toujours."""
    if not callable(fn):
        raise TypeError("fn must be callable")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def reduce_hors_memoire(morceaux: Iterable, reduce_fn: Callable, initial) -> dict:
    """Reduction LARGER-THAN-RAM : consomme les morceaux un a un (streaming paresseux), ne
    materialise jamais tout en memoire."""
    acc = initial
    n = 0
    for m in morceaux:
        acc = reduce_fn(acc, m)
        n += 1
    return {"resultat": acc, "morceaux_traites": n}


class CacheNoeudDag:
    """Cache par NOEUD de DAG, ADRESSE PAR CONTENU : cle = sha256(node_id + entrees). Un noeud dont
    les entrees n'ont pas change est servi du cache (pas de recalcul)."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}
        self._lock = threading.Lock()

    @staticmethod
    def cle(node_id: str, entrees) -> str:
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        try:
            brut = json.dumps(
                [node_id, entrees],
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise TypeError("entrees must be finite JSON data") from exc
        return hashlib.sha256(brut).hexdigest()

    def obtenir(self, node_id: str, entrees):
        with self._lock:
            return self._store.get(self.cle(node_id, entrees))

    def poser(self, node_id: str, entrees, valeur) -> None:
        with self._lock:
            self._store[self.cle(node_id, entrees)] = valeur

"""MLOps & observabilité — cœurs PURS, testés. Exécution du backlog :
ExperimentTracker (IDEA-74, tracking type MLflow), FeatureStore (IDEA-71, features versionnées),
lineage_record (IDEA-73, traçabilité), AuditChain (IDEA-96, journal d'audit inaltérable par
chaînage de hash), metric_alerts (IDEA-95, alerting intelligent). Aucun ordre.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import time


class ExperimentTracker:
    """Journalise chaque run d'expérience (params + métriques) en jsonl append-only."""

    def __init__(self, path: str):
        self.path = path

    def log_run(self, *, params: dict, metrics: dict) -> dict:
        row = {"params": params, "metrics": metrics, "_ts": time.time()}
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        return row

    def list_runs(self) -> list:
        out = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass
        return out

    def best_run(self, metric: str, *, maximize: bool = True):
        runs = [r for r in self.list_runs() if metric in r.get("metrics", {})]
        if not runs:
            return None
        key = lambda r: r["metrics"][metric]  # noqa: E731
        return max(runs, key=key) if maximize else min(runs, key=key)


class FeatureStore:
    """Stockage de features VERSIONNÉ (reproductibilité : on sait exactement ce qui a servi)."""

    def __init__(self, base: str):
        self.base = base

    def save(self, name: str, version: int, rows) -> str:
        os.makedirs(self.base, exist_ok=True)
        p = os.path.join(self.base, f"{name}.v{int(version)}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        return p

    def load(self, name: str, version: int) -> list:
        p = os.path.join(self.base, f"{name}.v{int(version)}.json")
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

    def versions(self, name: str) -> list:
        out = []
        for p in glob.glob(os.path.join(self.base, f"{name}.v*.json")):
            try:
                out.append(int(os.path.basename(p).split(".v")[1].split(".json")[0]))
            except (IndexError, ValueError):
                pass
        return sorted(out)


def lineage_record(dataset: str, *, source: str, transform: str, parents=None) -> dict:
    """Enregistrement de provenance : d'où vient une donnée et comment elle a été transformée."""
    return {"dataset": dataset, "source": source, "transform": transform,
            "parents": list(parents or []), "_ts": time.time()}


class AuditChain:
    """Journal d'audit INALTÉRABLE : chaque entrée chaîne le hash de la précédente. Toute
    modification a posteriori casse la chaîne (verify() renvoie False)."""

    GENESIS = "0" * 64

    def __init__(self):
        self.entries = []

    def append(self, event: dict) -> str:
        prev = self.entries[-1]["hash"] if self.entries else self.GENESIS
        payload = json.dumps(event, sort_keys=True, default=str)
        h = hashlib.sha256((prev + payload).encode("utf-8")).hexdigest()
        self.entries.append({"event": event, "prev": prev, "hash": h})
        return h

    def verify(self) -> bool:
        prev = self.GENESIS
        for e in self.entries:
            payload = json.dumps(e["event"], sort_keys=True, default=str)
            h = hashlib.sha256((prev + payload).encode("utf-8")).hexdigest()
            if h != e["hash"] or e["prev"] != prev:
                return False
            prev = h
        return True


def metric_alerts(metrics: dict, thresholds: dict) -> list:
    """Alerte si une métrique sort de ses bornes, ou si elle est ABSENTE (deny-by-default)."""
    alerts = []
    for name, rule in thresholds.items():
        if name not in metrics:
            alerts.append({"metric": name, "issue": "MISSING"})
            continue
        v = metrics[name]
        if "min" in rule and v < rule["min"]:
            alerts.append({"metric": name, "issue": "BELOW_MIN", "value": v})
        if "max" in rule and v > rule["max"]:
            alerts.append({"metric": name, "issue": "ABOVE_MAX", "value": v})
    return alerts

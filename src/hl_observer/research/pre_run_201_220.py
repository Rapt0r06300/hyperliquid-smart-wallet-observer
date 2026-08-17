"""Rigueur pre-run HyperSmart pour AUD-201/202/203/213/214/217/218/219.

Toutes les fonctions sont deterministes, stdlib-only et sans reseau. Elles
servent de primitives de preuve au laboratoire; elles ne peuvent ni signer ni
envoyer un ordre.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Mapping, Sequence


def minimum_track_record(
    returns: Sequence[float],
    *,
    z: float = 1.96,
    min_observations: int = 20,
    max_observations: int = 1_000_000,
) -> dict:
    """Estime le nombre minimal d'observations pour distinguer une moyenne de 0.

    Approximation conservatrice n >= (z*sigma/|mu|)^2. Si la moyenne est
    nulle/non mesurable, le track record requis est infini (represented by None)
    et la promotion reste impossible.
    """
    xs = [float(x) for x in returns if math.isfinite(float(x))]
    n = len(xs)
    if n < 2:
        return {"n_observe": n, "n_requis": None, "suffisant": False, "raison": "DONNEES_INSUFFISANTES"}
    mu = sum(xs) / n
    var = sum((x - mu) ** 2 for x in xs) / (n - 1)
    sigma = math.sqrt(max(0.0, var))
    if abs(mu) <= 1e-15:
        return {"n_observe": n, "n_requis": None, "suffisant": False, "raison": "EDGE_NUL"}
    n_req = int(math.ceil((float(z) * sigma / abs(mu)) ** 2))
    n_req = max(int(min_observations), min(int(max_observations), n_req))
    return {
        "n_observe": n,
        "n_requis": n_req,
        "suffisant": n >= n_req,
        "moyenne": mu,
        "ecart_type": sigma,
        "raison": None if n >= n_req else "TRACK_RECORD_TROP_COURT",
    }


def surveiller_drift_execution(
    baseline: Mapping[str, float],
    courant: Mapping[str, float],
    *,
    tolerances_relatives: Mapping[str, float] | None = None,
) -> dict:
    """Surveille le drift des couts, fills et latences sans inventer de zero."""
    tolerances = {
        "cost_bps": 0.20,
        "fill_rate": 0.10,
        "latency_ms": 0.25,
        **dict(tolerances_relatives or {}),
    }
    drift: dict[str, dict] = {}
    missing: list[str] = []
    for metric, tol in tolerances.items():
        if metric not in baseline or metric not in courant:
            missing.append(metric)
            continue
        b = float(baseline[metric])
        c = float(courant[metric])
        denom = max(abs(b), 1e-12)
        rel = abs(c - b) / denom
        if metric == "fill_rate":
            harmful = c < b and rel > tol
        else:
            harmful = c > b and rel > tol
        drift[metric] = {"baseline": b, "courant": c, "delta_relatif": rel, "tol": float(tol), "drift_nuisible": harmful}
    stable = not missing and not any(v["drift_nuisible"] for v in drift.values())
    return {"stable": stable, "missing": missing, "metrics": drift}


def detecter_change_points(
    values: Sequence[float],
    *,
    min_segment: int = 8,
    z_threshold: float = 3.0,
) -> dict:
    """Detecte la rupture de moyenne la plus forte, sans look-ahead externe."""
    xs = [float(x) for x in values]
    n = len(xs)
    if n < 2 * min_segment:
        return {"change": False, "index": None, "score": 0.0, "raison": "SERIE_TROP_COURTE"}
    best_score = 0.0
    best_idx = None
    for i in range(min_segment, n - min_segment + 1):
        a, b = xs[:i], xs[i:]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        va = sum((x - ma) ** 2 for x in a) / max(1, len(a) - 1)
        vb = sum((x - mb) ** 2 for x in b) / max(1, len(b) - 1)
        se = math.sqrt(va / len(a) + vb / len(b))
        score = abs(mb - ma) / max(se, 1e-12)
        if score > best_score:
            best_score, best_idx = score, i
    changed = bool(best_idx is not None and best_score >= z_threshold)
    return {"change": changed, "index": best_idx if changed else None, "score": best_score, "threshold": float(z_threshold)}


def verifier_reserve_tests_rares(
    tests: Sequence[Mapping[str, object]],
    *,
    tags_requis: Sequence[str],
) -> dict:
    """AUD-213: garde une reserve de tests rares separee des tests d'optimisation."""
    rares = [dict(t) for t in tests if bool(t.get("rare"))]
    tags = {str(t.get("tag")) for t in rares}
    missing = [str(tag) for tag in tags_requis if str(tag) not in tags]
    contaminated = [str(t.get("id", "?")) for t in rares if bool(t.get("used_for_tuning"))]
    return {
        "ok": not missing and not contaminated,
        "missing_tags": missing,
        "contamines_par_tuning": contaminated,
        "n_rares": len(rares),
    }


def verifier_budget_performance(
    mesures: Mapping[str, float],
    budgets_max: Mapping[str, float],
) -> dict:
    """AUD-214: fail-closed si une mesure requise manque ou depasse son budget."""
    missing = [k for k in budgets_max if k not in mesures]
    depassements = {
        k: {"mesure": float(mesures[k]), "budget": float(v)}
        for k, v in budgets_max.items()
        if k in mesures and float(mesures[k]) > float(v)
    }
    return {"ok": not missing and not depassements, "missing": missing, "depassements": depassements}


@dataclass
class ExclusiveLaunchGuard:
    """AUD-217: lock atomique qui interdit deux double-clics concurrents."""

    path: Path
    fd: int | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.write(self.fd, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(self.fd)
        return True

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "ExclusiveLaunchGuard":
        if not self.acquire():
            raise RuntimeError("DOUBLE_LAUNCH_REFUSED")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def retry_file_lock(
    operation: Callable[[], object],
    *,
    attempts: int = 4,
    sleep_s: float = 0.01,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """AUD-218: retente uniquement les PermissionError typiques AV/file-lock."""
    if attempts < 1:
        raise ValueError("attempts >= 1")
    last: PermissionError | None = None
    for n in range(1, attempts + 1):
        try:
            return {"ok": True, "attempts": n, "value": operation()}
        except PermissionError as exc:
            last = exc
            if n < attempts:
                sleeper(float(sleep_s))
    return {"ok": False, "attempts": attempts, "error": repr(last)}


def parse_decimal_invariant(text: str) -> Decimal:
    """AUD-219: parser numerique invariant, jamais dependant de la locale OS."""
    value = str(text).strip()
    if "," in value:
        raise ValueError("DECIMAL_COMMA_AMBIGUOUS")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("INVALID_DECIMAL") from exc


def parse_utc_invariant(text: str) -> datetime:
    """AUD-219: timestamp ISO-8601 transforme explicitement en UTC."""
    raw = str(text).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


__all__ = [
    "minimum_track_record",
    "surveiller_drift_execution",
    "detecter_change_points",
    "verifier_reserve_tests_rares",
    "verifier_budget_performance",
    "ExclusiveLaunchGuard",
    "retry_file_lock",
    "parse_decimal_invariant",
    "parse_utc_invariant",
]

"""T-2 / OPS-2 — Moniteur de santé agrégé.

Vérifie en un seul appel : crash signal, réseau HL, fraîcheur du moteur,
et espace disque. Paper-only, lecture seule.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("ALINA_PROJECT_ROOT", ".")).resolve()


def check_health(*, root: Path | None = None) -> dict:
    root = root or _project_root()
    checks: dict[str, dict] = {}

    checks["crash_signal"] = _check_crash_signal(root)
    checks["network"] = _check_network()
    checks["engine_freshness"] = _check_engine_freshness(root)
    checks["disk_space"] = _check_disk_space(root)

    all_ok = all(c.get("ok", False) for c in checks.values())
    return {"healthy": all_ok, "checks": checks, "ts": time.time()}


def _check_crash_signal(root: Path) -> dict:
    sig = root / "runtime" / "data" / "crash_signal.json"
    if not sig.exists():
        return {"ok": True, "detail": "no_crash_signal"}
    try:
        data = json.loads(sig.read_text(encoding="utf-8"))
        age_s = time.time() - float(data.get("ts", 0))
        return {"ok": False, "detail": "crash_detected", "reason": data.get("reason"), "age_s": round(age_s)}
    except (OSError, json.JSONDecodeError, ValueError):
        return {"ok": False, "detail": "crash_signal_unreadable"}


def _check_network() -> dict:
    try:
        from hl_observer.ops.network_health import check_hl_reachable
        result = check_hl_reachable(timeout=5)
        return {"ok": result["reachable"], "latency_ms": result.get("latency_ms")}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:200]}


def _check_engine_freshness(root: Path) -> dict:
    status_path = root / "runtime" / "data" / "hypersmart_engine_status.json"
    if not status_path.exists():
        return {"ok": False, "detail": "no_engine_status"}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8-sig"))
        updated_ms = int(data.get("updated_at_ms", 0))
        age_s = (time.time() * 1000 - updated_ms) / 1000
        stale = age_s > 120
        return {"ok": not stale, "age_s": round(age_s), "phase": data.get("phase")}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"ok": False, "detail": str(exc)[:200]}


def _check_disk_space(root: Path) -> dict:
    try:
        import shutil
        usage = shutil.disk_usage(str(root))
        free_mb = usage.free / (1024 * 1024)
        return {"ok": free_mb > 500, "free_mb": round(free_mb)}
    except Exception as exc:
        return {"ok": True, "detail": f"check_skipped: {exc}"}


__all__ = ["check_health"]

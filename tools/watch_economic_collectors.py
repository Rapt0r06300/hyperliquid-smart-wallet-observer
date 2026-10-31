"""Low-priority local watchdog for the bounded paper-data campaign."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.copy_vault_protocol import (  # noqa: E402
    CHECKPOINT_COLLECTOR_PROTOCOL,
    UNBOUND_L2_SOURCE_PROTOCOL,
)
from hl_observer.ops.bounded_collection import (  # noqa: E402
    STATE_RELPATH,
    ensure_bounded_collectors,
    renew_bounded_collection_lease,
)
from hl_observer.ops.collecteur_registry import (  # noqa: E402
    COLLECTEURS_CAMPAGNE,
    REGISTRE,
)

DEFAULT_NAMES = (
    "allmids-collector",
    "bbo-collector",
    "native-venues",
    "carnet-collector",
    "venues-collector",
    "marks-collector",
    "liq-collector",
    "overshoot-collector",
    "vault-collector",
    "scorer-vaults",
    "backfill-fills",
    "backfill-candles-vaults",
    "userfills-live",
    "copy-vault-checkpoints",
)
_COLLECTOR_REGISTRY = {
    str(row["nom"]): row for row in (*REGISTRE, *COLLECTEURS_CAMPAGNE)
}


def _idle_priority() -> None:
    if os.name == "nt":
        ctypes.windll.kernel32.SetPriorityClass(  # type: ignore[attr-defined]
            ctypes.windll.kernel32.GetCurrentProcess(), 0x40
        )


def _requested_names(root: Path) -> list[str]:
    try:
        state = json.loads((root / STATE_RELPATH).read_text(encoding="utf-8"))
        requested = [str(name) for name in state.get("requested") or () if name]
    except (OSError, TypeError, ValueError):
        requested = []
    return list(dict.fromkeys(requested or DEFAULT_NAMES))


def _append_log(root: Path, payload: dict[str, Any]) -> None:
    path = root / "runtime" / "logs" / "economic-collector-watchdog.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _file_status(path: Path, *, now: float) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError as exc:
        return {"path": str(path.resolve()), "exists": False, "error": type(exc).__name__}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "age_s": round(max(0.0, now - stat.st_mtime), 1),
    }


def _tail(path: Path, *, lines: int = 2, max_bytes: int = 8192) -> list[str]:
    """Read a small bounded log tail for the live console, not the full log."""
    if lines <= 0 or max_bytes <= 0:
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            data = handle.read(max_bytes)
    except OSError:
        return []
    decoded = data.decode("utf-8", errors="replace")
    return decoded.splitlines()[-lines:]


def _collector_details(root: Path, names: Sequence[str], active: Mapping[str, Any]) -> list[dict[str, Any]]:
    now = time.time()
    details: list[dict[str, Any]] = []
    for name in names:
        row = _COLLECTOR_REGISTRY.get(name, {})
        log_paths = (
            root / "runtime" / "logs" / f"economic-{name}.log",
            root / "runtime" / "logs" / f"{name}.log",
        )
        present_logs = []
        for path in log_paths:
            observation = _file_status(path, now=now)
            if observation["exists"]:
                present_logs.append({**observation, "tail": _tail(path, lines=2)})
        present_logs.sort(key=lambda item: str(item.get("modified_at") or ""), reverse=True)
        expected_log = log_paths[0] if name in active else log_paths[1]
        heartbeat_rel = row.get("heartbeat")
        heartbeat_paths = [root / str(heartbeat_rel)] if heartbeat_rel else []
        canonical_heartbeat = root / "runtime" / "research_lab" / "heartbeats" / f"{name}.json"
        if canonical_heartbeat not in heartbeat_paths:
            heartbeat_paths.append(canonical_heartbeat)
        heartbeat_observations = [
            _file_status(path, now=now)
            for path in heartbeat_paths
            if path.is_file()
        ]
        details.append({
            "name": name,
            "state": "ACTIVE" if name in active else "MISSING",
            "pid": active.get(name),
            "logs": present_logs,
            "expected_log": str(expected_log.resolve()),
            "heartbeats": heartbeat_observations,
        })
    return details


def run_watchdog(
    root: Path,
    *,
    interval_s: float,
    duration_s: float,
    lease_duration_s: float | None = None,
    requested_names: Sequence[str] | None = None,
    ensure_fn: Callable[..., dict[str, Any]] = ensure_bounded_collectors,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    max_passes: int | None = None,
) -> int:
    deadline = monotonic_fn() + max(0.0, float(duration_s))
    passes = 0
    while monotonic_fn() < deadline:
        names = (
            list(dict.fromkeys(str(name) for name in requested_names if name))
            if requested_names is not None
            else _requested_names(root)
        )
        try:
            result = ensure_fn(
                root,
                names,
                duration_s=float(lease_duration_s or duration_s),
                startup_wait_s=5.0,
            )
            lease_id = str((result.get("lease") or {}).get("lease_id") or "")
            renewal = (
                renew_bounded_collection_lease(
                    root,
                    lease_id,
                    duration_s=float(lease_duration_s or duration_s),
                )
                if lease_id
                else {"renewed": False, "reason": "LEASE_ID_MISSING"}
            )
            active_map = result.get("actifs")
            if not isinstance(active_map, Mapping):
                # The first start result reports verified wrappers under `pids`;
                # subsequent inspections expose the same inventory as `actifs`.
                active_map = result.get("pids")
            if not isinstance(active_map, Mapping):
                active_map = {}
            active = sorted(str(name) for name in active_map)
            missing = list(result.get("manquants") or ())
            missing.extend(name for name in names if name not in active and name not in missing)
            protocols = result.get("protocols") or {}
            fills_protocol = str(protocols.get("userfills-live") or "")
            checkpoint_protocol = str(protocols.get("copy-vault-checkpoints") or "")
            protocol_status = (
                "OK"
                if "userfills-live" in active
                and "copy-vault-checkpoints" in active
                and fills_protocol == UNBOUND_L2_SOURCE_PROTOCOL
                and checkpoint_protocol == CHECKPOINT_COLLECTOR_PROTOCOL
                else "ATTENTE HEARTBEATS"
                if not fills_protocol and not checkpoint_protocol
                else "À CORRIGER"
                if fills_protocol not in {"", UNBOUND_L2_SOURCE_PROTOCOL}
                or checkpoint_protocol not in {"", CHECKPOINT_COLLECTOR_PROTOCOL}
                else "EN COURS"
            )
            processes_ready = not missing and len(active) == len(names)
            status = (
                "ACTIVE"
                if processes_ready and renewal.get("renewed") and protocol_status == "OK"
                else "STARTING"
                if processes_ready and renewal.get("renewed") and protocol_status in {"ATTENTE HEARTBEATS", "EN COURS"}
                else "DEGRADED"
            )
            record = {
                "ts_ms": int(time.time() * 1000),
                "status": status,
                "requested": names,
                "active": active,
                "missing": missing,
                "lease_id": lease_id or None,
                "lease_renewal": renewal.get("reason"),
                "causal_protocol_status": protocol_status,
                "observed_protocols": {
                    "userfills-live": fills_protocol or None,
                    "copy-vault-checkpoints": checkpoint_protocol or None,
                },
                "paper_read_only": result.get("paper_read_only") is True,
                "real_execution": False,
            }
            details = _collector_details(root, names, active_map)
            record["collector_details"] = details
            print(
                f"[COLLECTE COPY-VAULT] {status} — processus {len(active)}/{len(names)}; "
                f"manquants: {', '.join(missing) if missing else 'aucun'}; "
                f"protocole causal: {protocol_status}; bail: {lease_id or 'indisponible'}",
                flush=True,
            )
            print(
                "[JOURNAUX] Dernières lignes de chaque collecteur ci-dessous; "
                "journaux complets conservés avec rotation bornée dans runtime\\logs.",
                flush=True,
            )
            for index, detail in enumerate(details, 1):
                log = detail["logs"][0] if detail["logs"] else None
                heartbeat = max(
                    detail["heartbeats"], key=lambda item: float(item.get("age_s", 0.0)) * -1,
                    default=None,
                )
                log_text = (
                    f"journal={log['path']} · {log['bytes']:,} octets · modifié il y a {log['age_s']} s"
                    if log else f"journal en attente={detail['expected_log']}"
                )
                heartbeat_text = (
                    f"heartbeat={heartbeat['path']} · modifié il y a {heartbeat['age_s']} s"
                    if heartbeat else "heartbeat=pas encore observé"
                )
                process_text = (
                    f"PID {detail['pid']}" if detail["state"] == "ACTIVE" else "ABSENT"
                )
                print(
                    f"  [{index:02d}/{len(details):02d}] {detail['name']} · {process_text} · "
                    f"{log_text} · {heartbeat_text}",
                    flush=True,
                )
                if log:
                    for line in log.get("tail", ()):
                        visible_line = str(line).replace("\r", " ").replace("\n", " ")
                        print(f"       derniere sortie: {visible_line[:240]}", flush=True)
            if protocol_status == "À CORRIGER":
                print(
                    f"[PROTOCOLE] userfills={fills_protocol or 'absent'}; "
                    f"checkpoints={checkpoint_protocol or 'absent'}; aucune preuve causale "
                    "ne doit être admise tant que les deux protocoles attendus ne sont pas actifs",
                    flush=True,
                )
            if not renewal.get("renewed"):
                print(
                    f"[BAIL] renouvellement non confirmé ({renewal.get('reason')}); "
                    "le superviseur réessaiera au prochain cycle",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001 - watchdog must survive a transient failure
            record = {
                "ts_ms": int(time.time() * 1000),
                "status": "WATCH_PASS_ERROR",
                "requested": names,
                "error": f"{type(exc).__name__}: {exc}",
                "paper_read_only": True,
                "real_execution": False,
            }
            print(
                f"[COLLECTE COPY-VAULT] ERREUR {type(exc).__name__}; nouvelle tentative au prochain cycle; "
                "voir runtime/logs/economic-collector-watchdog.jsonl",
                flush=True,
            )
        _append_log(root, record)
        passes += 1
        if max_passes is not None and passes >= int(max_passes):
            break
        remaining = deadline - monotonic_fn()
        if remaining <= 0:
            break
        sleep_fn(min(max(1.0, float(interval_s)), remaining))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument(
        "--profile",
        choices=("resume", "copy-vault"),
        default="resume",
        help="resume the saved request or force the complete Copy-Vault collector set",
    )
    parser.add_argument("--interval-s", type=float, default=30.0)
    parser.add_argument("--duration-s", type=float, default=7 * 24 * 60 * 60)
    parser.add_argument(
        "--lease-duration-s",
        type=float,
        help="collector lease TTL renewed while this watchdog runs; bounded to seven days",
    )
    args = parser.parse_args(argv)
    _idle_priority()
    requested_names = list(DEFAULT_NAMES) if args.profile == "copy-vault" else None
    try:
        return run_watchdog(
            Path(args.root).resolve(),
            interval_s=args.interval_s,
            duration_s=args.duration_s,
            lease_duration_s=args.lease_duration_s,
            requested_names=requested_names,
        )
    except KeyboardInterrupt:
        print(
            "\n[ARRÊT] Ctrl+C reçu. Le bail n'est plus renouvelé; les collecteurs liés à cette campagne s'arrêteront à son expiration.",
            flush=True,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

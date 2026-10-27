"""Low-priority local watchdog for the bounded paper-data campaign."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.ops.bounded_collection import (  # noqa: E402
    STATE_RELPATH,
    ensure_bounded_collectors,
    renew_bounded_collection_lease,
)
from hl_observer.backtesting.copy_vault_protocol import (  # noqa: E402
    CHECKPOINT_COLLECTOR_PROTOCOL,
    UNBOUND_L2_SOURCE_PROTOCOL,
)

DEFAULT_NAMES = (
    "allmids-collector",
    "bbo-collector",
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
_WATCHDOG_LOG_MAX_BYTES = 2 * 1024 * 1024
_WATCHDOG_LOG_BACKUPS = 3


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
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    line_bytes = len(line.encode("utf-8"))
    if path.exists() and path.stat().st_size + line_bytes > _WATCHDOG_LOG_MAX_BYTES:
        try:
            for index in range(_WATCHDOG_LOG_BACKUPS, 0, -1):
                source = path if index == 1 else path.with_name(f"{path.name}.{index - 1}")
                target = path.with_name(f"{path.name}.{index}")
                if source.exists():
                    source.replace(target)
        except OSError:
            # The next pass retries rotation; transient Windows file locks must
            # not terminate the lease-renewing collector supervisor.
            pass
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)


def _last_collector_log_line(root: Path, name: str, *, max_bytes: int = 8_192) -> str:
    path = root / "runtime" / "logs" / f"economic-{name}.log"
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return "journal absent ou illisible"
    if not lines:
        return "journal vide"
    return lines[-1].strip()[-240:] or "dernière ligne vide"


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
            workers_ready = (
                not missing and len(active) == len(names) and renewal.get("renewed")
            )
            status = (
                "DEGRADED"
                if not workers_ready or protocol_status == "À CORRIGER"
                else "ACTIVE"
                if protocol_status == "OK"
                else "STARTING"
                if protocol_status in {"ATTENTE HEARTBEATS", "EN COURS"}
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
            print(
                "[COLLECTE COPY-VAULT] %s — processus %d/%d; manquants: %s; protocole causal: %s; bail: %s"
                % (
                    status,
                    len(active),
                    len(names),
                    ", ".join(missing) if missing else "aucun",
                    protocol_status,
                    lease_id or "indisponible",
                ),
                flush=True,
            )
            for name in names:
                pid = active_map.get(name)
                worker_status = f"PID {pid}" if pid is not None else "ABSENT"
                print(
                    "  [WORKER] %s — %s — %s"
                    % (name, worker_status, _last_collector_log_line(root, name)),
                    flush=True,
                )
            if protocol_status == "À CORRIGER":
                print(
                    "[PROTOCOLE] userfills=%s; checkpoints=%s; aucune preuve causale ne doit être admise tant que les deux protocoles attendus ne sont pas actifs"
                    % (fills_protocol or "absent", checkpoint_protocol or "absent"),
                    flush=True,
                )
            if not renewal.get("renewed"):
                print(
                    "[BAIL] renouvellement non confirmé (%s); le superviseur réessaiera au prochain cycle"
                    % renewal.get("reason"),
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
                "[COLLECTE COPY-VAULT] ERREUR %s; nouvelle tentative au prochain cycle; voir runtime/logs/economic-collector-watchdog.jsonl"
                % type(exc).__name__,
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

"""Forward-only causal L2 checkpoints for Copy-Vault economic evidence.

The main ``userfills-live`` collector owns the live fill stream.  This small
companion tails only bytes appended after its first startup and captures public
Hyperliquid ``/info`` L2 books after predeclared REFERENCE, ENTRY and EXIT
instants.  It never reads historical books, interpolates a quote, or performs
an exchange action.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_executable import (
    CHECKPOINT_COLLECTOR_PROTOCOL,
    canonical_metaorder_id,
    classify_live_entry_action,
    expected_open_direction,
)
from hl_observer.backtesting.copy_vault_protocol import (
    CHECKPOINT_WRITER_STATE_SCHEMA,
    INSTRUMENT_IDENTITY_SCHEMA,
)
from hl_observer.collection import copy_vault_gap_windows as GAPS
from hl_observer.collection.copy_vault_checkpoint_socle import (
    INFO_URL,
    MAX_TARGET_LAG_MS,
    _append_jsonl,
    _file_identity,
    _parse_book,
    _strict_int,
    fetch_hyperliquid_l2_book,
)
from hl_observer.collection.copy_vault_presignal_lane import (
    LANE_RELPATH,
    VoiePreSignal,
)
from hl_observer.collection.vault_fills_backfill import canonical_fill_id
from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.ops.echec_silencieux import noter as _noter_echec

SCHEMA_VERSION = CHECKPOINT_WRITER_STATE_SCHEMA
COMPANION_PROTOCOL = CHECKPOINT_COLLECTOR_PROTOCOL
INPUT_RELPATH = Path("runtime") / "data" / "vault_fills_live.jsonl"
OUTPUT_RELPATH = Path("runtime") / "data" / "copy_vault_l2_tape.jsonl"
STATE_RELPATH = Path("runtime") / "data" / "copy_vault_checkpoint_tail_state.json"

COPY_DELAY_MS = 60_000
HORIZONS_MS = (30_000, 60_000, 120_000, 180_000, 300_000, 900_000, 1_800_000, 3_600_000)
METAORDER_GAP_MS = 60_000
CONTINUATION_SIGNAL_FILL_COUNT = 3
MAX_EVENT_IDS = 20_000
MAX_CHECKPOINT_IDS = 20_000
MAX_PENDING = 5_000
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

BookFetcher = Callable[[str], Mapping[str, Any] | None]
Clock = Callable[[], int]


def _snapshot_marker(fill: Mapping[str, Any]) -> Any:
    markers = [
        fill[name]
        for name in ("isSnapshot", "is_snapshot")
        if name in fill
    ]
    if not markers or any(type(marker) is not bool for marker in markers):
        return None
    if len(set(markers)) != 1:
        return None
    return markers[0]


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        try:
            temporary.unlink()
        except OSError as exc:
            _noter_echec("collection/copy_vault_checkpoint_tail.py:temporary_unlink", exc)


def _default_state(*, offset: int, output_offset: int, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instrument_identity_schema": INSTRUMENT_IDENTITY_SCHEMA,
        "paper_read_only": True,
        "real_execution": False,
        "protocol": COMPANION_PROTOCOL,
        "initialized_at_ms": int(now_ms),
        "writer_run_id": "copy-writer-" + secrets.token_hex(8),
        "clean_epoch_ms": int(now_ms),
        "input_offset": max(0, int(offset)),
        "output_start_offset": max(0, int(output_offset)),
        # 16/11/2026 — JOURNAL DES FENETRES DE TROU. Les compteurs ci-dessous sont cumulatifs
        # sur tout le run : un seul incident fermait l'epoque entiere cote lecteur. On publie
        # desormais OU se situe chaque trou, pour que le lecteur segmente au lieu de tout refuser.
        # Les compteurs ne sont JAMAIS remis a zero : un trou historique reste un trou historique.
        "gap_windows_schema": GAPS.SCHEMA_FENETRES,
        "gap_windows": [],
        "gap_windows_dropped": 0,
        "last_input_received_ms": 0,
        "lane_offset": 0,
        "lane_file_identity": None,
        "recent_event_ids": [],
        "captured_checkpoint_ids": [],
        "metaorder_state": {},
        "pending": [],
        "counters": {
            "complete_lines": 0,
            "valid_live_fills": 0,
            "duplicates_rejected": 0,
            "invalid_rejected": 0,
            "non_entry_rejected": 0,
            "direction_contradictions_rejected": 0,
            "stale_rejected": 0,
            "out_of_order_rejected": 0,
            "metaorders_started": 0,
            "continuations": 0,
            "continuation_signals_started": 0,
            "checkpoints_captured": 0,
            "checkpoints_expired": 0,
            "fetch_retries": 0,
            "input_rotations": 0,
            "reconnect_backfill_blocked": 0,
            "writer_outages": 0,
            "pending_overflow_rejected": 0,
            "identity_migration_resets": 0,
            # 16/11/2026 — liaison du carnet de REFERENCE pré-signal (bloqueur P0).
            "reference_bound_presignal": 0,
            "reference_no_presignal_book": 0,
            "reference_presignal_too_old": 0,
        },
    }


def _event_identity(fill: Mapping[str, Any]) -> str:
    return canonical_fill_id(fill)


def coverage_receipt(counters: Mapping[str, Any], *, expected_lines: int) -> dict[str, Any]:
    """Summarize exact checkpoint coverage without assuming missing lines."""
    if isinstance(expected_lines, bool) or not isinstance(expected_lines, int) or expected_lines < 0:
        return {"status": "UNMEASURABLE", "reason": "EXPECTED_LINES_INVALID", "paper_read_only": True}
    required = (
        "complete_lines", "checkpoints_captured", "reconnect_backfill_blocked",
        "invalid_rejected", "input_rotations", "checkpoints_expired",
        "pending_overflow_rejected",
    )
    values = {name: counters.get(name) for name in required}
    actual = values["complete_lines"]
    captured = values["checkpoints_captured"]
    if any(type(value) is not int or value < 0 for value in (actual, captured)):
        return {"status": "UNMEASURABLE", "reason": "COUNTER_INVALID", "paper_read_only": True}
    complete_counters = all(type(value) is int and value >= 0 for value in values.values())
    valid_incidents = {
        name: value if type(value) is int and value >= 0 else 0
        for name, value in values.items()
        if name not in ("complete_lines", "checkpoints_captured")
    }
    # Une rotation incrémente aussi reconnect_backfill_blocked : compter
    # l'incident une seule fois, sans masquer les expirations et débordements.
    gaps = (
        max(valid_incidents["reconnect_backfill_blocked"], valid_incidents["input_rotations"])
        + valid_incidents["invalid_rejected"]
        + valid_incidents["checkpoints_expired"]
        + valid_incidents["pending_overflow_rejected"]
        # Compteur ne le 17/11 : absent d'un etat anterieur, il vaut zero.
        + (counters.get("writer_outages") if type(counters.get("writer_outages")) is int
           and counters.get("writer_outages") > 0 else 0)
    )
    return {
        "status": "PROVEN" if complete_counters and actual == expected_lines and gaps == 0 else "UNMEASURABLE",
        "reason": None if complete_counters else "COUNTERS_INCOMPLETE_OR_INVALID",
        "expected_lines": expected_lines,
        "complete_lines": actual,
        "checkpoints_captured": captured,
        "gap_count": gaps,
        "paper_read_only": True,
        "real_execution": False,
    }


def _trim(values: list[str], limit: int) -> list[str]:
    return values[-max(1, int(limit)) :]


def _valid_state_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


class CopyVaultCheckpointTail(VoiePreSignal):
    """Durable forward-only tail and causal checkpoint scheduler."""

    def __init__(
        self,
        root: str | Path,
        *,
        fetch_book: BookFetcher = fetch_hyperliquid_l2_book,
        clock_ms: Clock | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.input_path = self.root / INPUT_RELPATH
        self.output_path = self.root / OUTPUT_RELPATH
        self.state_path = self.root / STATE_RELPATH
        self.lane_path = self.root / LANE_RELPATH
        self.fetch_book = fetch_book
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        # Carnets WS récents par coin, en MEMOIRE seulement : au redémarrage on repart du bout du
        # ruban, ce qui refuse des liaisons pendant quelques secondes au lieu d'en inventer.
        self._dernier_carnet: dict[str, list[dict[str, Any]]] = {}
        self.state = self._load_or_initialize()

    def _load_or_initialize(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            loaded = None
        preserved_loaded = loaded
        if (
            isinstance(loaded, dict)
            and loaded.get("schema_version") == SCHEMA_VERSION
            and loaded.get("instrument_identity_schema") == INSTRUMENT_IDENTITY_SCHEMA
            and loaded.get("paper_read_only") is True
            and loaded.get("real_execution") is False
            and loaded.get("protocol") == COMPANION_PROTOCOL
        ):
            critical_state_fields = ("input_offset", "output_start_offset", "clean_epoch_ms")
            if (
                any(
                    not _valid_state_nonnegative_int(loaded.get(field))
                    for field in critical_state_fields
                )
                or not isinstance(loaded.get("pending"), list)
                or not isinstance(loaded.get("recent_event_ids"), list)
                or not isinstance(loaded.get("captured_checkpoint_ids"), list)
                or not isinstance(loaded.get("metaorder_state"), dict)
                or not isinstance(loaded.get("writer_run_id"), str)
            ):
                loaded = None
        if (
            isinstance(loaded, dict)
            and loaded.get("schema_version") == SCHEMA_VERSION
            and loaded.get("instrument_identity_schema") == INSTRUMENT_IDENTITY_SCHEMA
            and loaded.get("paper_read_only") is True
            and loaded.get("real_execution") is False
            and loaded.get("protocol") == COMPANION_PROTOCOL
        ):
            counters = loaded.get("counters")
            if not isinstance(counters, dict):
                counters = {}
                loaded["counters"] = counters
            defaults = _default_state(
                offset=0, output_offset=0, now_ms=self.clock_ms()
            )["counters"]
            for name, value in defaults.items():
                counters.setdefault(name, value)
            if "input_file_identity" not in loaded:
                try:
                    loaded["input_file_identity"] = _file_identity(self.input_path.stat())
                except OSError:
                    loaded["input_file_identity"] = None
            # 16/11/2026 — MIGRATION HONNETE VERS LE JOURNAL DE FENETRES. Un etat ecrit par
            # l'ancien code n'a pas de journal. Deux cas, et un seul est certifiable :
            #  * les trois compteurs de trou sont EXACTEMENT a zero -> il n'y a rien a expliquer,
            #    on peut ouvrir le journal vide sans mentir ;
            #  * un compteur est non nul -> les trous existent mais leur POSITION est perdue. On
            #    n'ouvre PAS le journal : le lecteur restera ferme, et la raison le dira. Aucune
            #    reparation retroactive : c'est exactement le cas du run du 16/11 (43 expirations,
            #    1 rotation) et il doit rester non certifiable.
            if loaded.get("gap_windows_schema") != GAPS.SCHEMA_FENETRES:
                anciens = [loaded["counters"].get(nom) for nom in GAPS.COMPTEUR_PAR_NATURE.values()]
                if all(type(v) is int and v == 0 for v in anciens):
                    loaded["gap_windows_schema"] = GAPS.SCHEMA_FENETRES
                    loaded["gap_windows"] = []
                    loaded["gap_windows_dropped"] = 0
                else:
                    loaded["gap_windows_unavailable_reason"] = (
                        "TROUS_ANTERIEURS_SANS_FENETRE:" + ",".join(
                            f"{nom}={loaded['counters'].get(nom)}"
                            for nom in GAPS.COMPTEUR_PAR_NATURE.values()))
            loaded.setdefault("last_input_received_ms", 0)
            if isinstance(loaded.get("gap_windows"), list):
                # Un incident = un intervalle (union et sommes conservees) : voir GAPS.compacter.
                loaded["gap_windows"] = GAPS.compacter(loaded["gap_windows"])
            return loaded
        try:
            offset = self.input_path.stat().st_size
        except OSError:
            offset = 0
        try:
            output_offset = self.output_path.stat().st_size
        except OSError:
            output_offset = 0
        state = _default_state(
            offset=offset, output_offset=output_offset, now_ms=self.clock_ms()
        )
        if isinstance(preserved_loaded, dict):
            archived_state_path = self.state_path.with_name(
                f"{self.state_path.name}.identity-migration-{time.time_ns()}.json"
            )
            _atomic_write(archived_state_path, preserved_loaded)
            state["identity_migration_reset"] = {
                "reason": "INSTRUMENT_IDENTITY_SCHEMA_CHANGED_OR_UNVERIFIED",
                "previous_schema_version": preserved_loaded.get("schema_version"),
                "previous_instrument_identity_schema": preserved_loaded.get(
                    "instrument_identity_schema"
                ),
                "preserved_state_path": str(archived_state_path.relative_to(self.root)),
            }
            state["counters"]["identity_migration_resets"] = 1
        try:
            state["input_file_identity"] = _file_identity(self.input_path.stat())
        except OSError:
            state["input_file_identity"] = None
        _atomic_write(self.state_path, state)
        return state

    def _read_appended_lines(self) -> list[dict[str, Any]]:
        try:
            handle = self.input_path.open("rb")
        except OSError:
            return []
        with handle:
            stat = os.fstat(handle.fileno())
            size = int(stat.st_size)
            identity = _file_identity(stat)
            offset = int(self.state.get("input_offset") or 0)
            prior_identity = self.state.get("input_file_identity")
            input_rotated = (prior_identity is not None and prior_identity != identity) or size < offset
            if input_rotated:
                offset = 0
                # A replacement file may already contain a reconnect snapshot or
                # REST backfill. Baseline it atomically: only bytes appended after
                # this observed identity change may enter the causal live tail.
                self.state["input_offset"] = size
                self.state["counters"]["input_rotations"] += 1
                self.state["counters"]["reconnect_backfill_blocked"] += 1
                detecte_ms = self.clock_ms()
                # Les octets entre l'ancien offset et la taille du remplacant ne seront JAMAIS
                # lus. On ne sait pas ce qu'ils contenaient : la fenetre va donc de la derniere
                # ligne reellement ingeree (ou du debut de l'epoque, si on n'en a aucune) a
                # l'instant de la detection. C'est conservateur, et c'est le point : on ne
                # certifie pas une periode dont on ignore ce qu'on a manque.
                depuis = int(self.state.get("last_input_received_ms") or 0) or int(
                    self.state.get("clean_epoch_ms") or detecte_ms)
                GAPS.ajouter_fenetre(self.state, GAPS.fenetre(
                    GAPS.TROU_ROTATION, debut_ms=depuis, fin_ms=detecte_ms))
                self.state["last_reconnect_epoch_ms"] = detecte_ms
                self.state["input_file_identity"] = identity
                return []
            self.state["input_file_identity"] = identity
            if size == offset:
                return []
            try:
                handle.seek(offset)
                chunk = handle.read()
            except OSError:
                return []
        complete_end = chunk.rfind(b"\n")
        if complete_end < 0:
            return []
        consumed = chunk[: complete_end + 1]
        self.state["input_offset"] = offset + len(consumed)
        rows: list[dict[str, Any]] = []
        for line in consumed.splitlines():
            if not line.strip():
                continue
            self.state["counters"]["complete_lines"] += 1
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, TypeError):
                self.state["counters"]["invalid_rejected"] += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
                recu = row.get("received_at_ms")
                if type(recu) is int and recu > int(self.state.get("last_input_received_ms") or 0):
                    self.state["last_input_received_ms"] = recu
            else:
                self.state["counters"]["invalid_rejected"] += 1
        return rows

    def _enqueue_checkpoints(self, additions: list[dict[str, Any]]) -> bool:
        """Admit one logical checkpoint batch or reject it visibly as a unit."""

        pending = list(self.state.get("pending") or [])
        if len(pending) + len(additions) > MAX_PENDING:
            counters = self.state["counters"]
            counters["pending_overflow_rejected"] = int(
                counters.get("pending_overflow_rejected") or 0
            ) + len(additions)
            # Ce lot de checkpoints n'existera jamais : la fenetre couvre les instants qu'il
            # devait observer. `n` vaut le nombre d'unites de compteur, pour que la
            # reconciliation « somme des fenetres == compteur » tienne exactement.
            cibles = [int(x.get("target_wall_ms") or 0) for x in additions
                      if type(x.get("target_wall_ms")) is int]
            maintenant = self.clock_ms()
            GAPS.ajouter_fenetre(self.state, GAPS.fenetre(
                GAPS.TROU_DEBORDEMENT,
                debut_ms=min(cibles) if cibles else maintenant,
                fin_ms=max(cibles) if cibles else maintenant,
                n=len(additions)))
            return False
        pending.extend(additions)
        self.state["pending"] = pending
        return True

    def _schedule_fill(self, fill: Mapping[str, Any], *, now_ms: int) -> None:
        try:
            vault = str(fill["vault"]).lower()
            coin = preserve_native_instrument_symbol(fill["coin"])
            direction_raw = fill.get("signe") if "signe" in fill else fill.get("sens")
            direction = _strict_int(direction_raw, "direction")
            fill_ts_ms = _strict_int(fill["ts_ms"], "ts_ms")
            received_at_ms = _strict_int(fill["received_at_ms"], "received_at_ms")
        except (KeyError, TypeError, ValueError, OverflowError):
            self.state["counters"]["invalid_rejected"] += 1
            return
        if (
            fill.get("source") != "LIVE_WS"
            or _snapshot_marker(fill) is not False
            or not ADDRESS_RE.fullmatch(vault)
            or not coin
            or direction not in (-1, 1)
            or fill_ts_ms <= 0
            or received_at_ms < fill_ts_ms
            or received_at_ms - fill_ts_ms > MAX_TARGET_LAG_MS
        ):
            self.state["counters"]["invalid_rejected"] += 1
            return
        expected_direction = expected_open_direction(fill)
        if expected_direction is None:
            meta_state = dict(self.state.get("metaorder_state") or {})
            meta_state.pop(f"{vault}|{coin}", None)
            self.state["metaorder_state"] = meta_state
            self.state["counters"]["non_entry_rejected"] += 1
            return
        if direction != expected_direction:
            self.state["counters"]["direction_contradictions_rejected"] += 1
            return
        entry_action = classify_live_entry_action(fill)
        if entry_action is None:
            self.state["counters"]["non_entry_rejected"] += 1
            return
        if now_ms < received_at_ms or now_ms - received_at_ms > MAX_TARGET_LAG_MS:
            self.state["counters"]["stale_rejected"] += 1
            return
        event_id = _event_identity(fill)
        recent = list(self.state.get("recent_event_ids") or [])
        if event_id in set(recent):
            self.state["counters"]["duplicates_rejected"] += 1
            return
        recent.append(event_id)
        self.state["recent_event_ids"] = _trim(recent, MAX_EVENT_IDS)
        self.state["counters"]["valid_live_fills"] += 1

        key = f"{vault}|{coin}"
        meta_state = dict(self.state.get("metaorder_state") or {})
        previous = meta_state.get(key) if isinstance(meta_state.get(key), dict) else None
        if previous is not None and fill_ts_ms < int(previous.get("last_fill_ts_ms") or 0):
            self.state["counters"]["out_of_order_rejected"] += 1
            return
        continuation = bool(
            entry_action == "ADD"
            and previous
            and int(previous.get("direction") or 0) == direction
            and fill_ts_ms - int(previous.get("last_fill_ts_ms") or 0) <= METAORDER_GAP_MS
        )
        if continuation:
            previous["last_fill_ts_ms"] = fill_ts_ms
            previous["fill_count"] = max(1, int(previous.get("fill_count") or 1)) + 1
            if (
                int(previous["fill_count"]) == CONTINUATION_SIGNAL_FILL_COUNT
                and not previous.get("continuation_metaorder_id")
            ):
                continuation_id = canonical_metaorder_id(
                    vault=vault,
                    coin=coin,
                    direction=direction,
                    signal_ts_ms=received_at_ms,
                    first_event_id=event_id,
                )
                previous["continuation_metaorder_id"] = continuation_id
                base = {
                    "coin": coin,
                    "vault": vault,
                    "direction": direction,
                    "signal_ts_ms": received_at_ms,
                    "signal_event_id": event_id,
                    "signal_action": entry_action,
                    "metaorder_id": continuation_id,
                    "attempts": 0,
                }
                # REFERENCE : carnet DEJA RECU avant le signal, ecrit tout de suite (bloqueur
                # P0). ENTRY/EXIT restent des observations posterieures a leur cible, ce que la
                # spec autorise explicitement.
                #
                # REPLI : si aucun carnet pre-signal n'est eligible, on programme l'ancienne
                # requete REST. Elle sera refusee par l'executeur (`REFERENCE_NOT_AVAILABLE_AT_
                # SIGNAL`) — c'est le point : le refus reste VISIBLE avec son motif, au lieu de
                # disparaitre en « aucune reference ». Un seul des deux chemins s'execute, donc
                # l'identifiant de checkpoint reste unique.
                a_venir = [{
                    **base,
                    "stage": "ENTRY",
                    "checkpoint_id": f"{continuation_id}:ENTRY",
                    "target_wall_ms": received_at_ms + COPY_DELAY_MS,
                }]
                if not self._emettre_reference_liee(base, signal_received_ms=received_at_ms):
                    a_venir.insert(0, {
                        **base,
                        "stage": "REFERENCE",
                        "checkpoint_id": f"{continuation_id}:REFERENCE",
                        "target_wall_ms": received_at_ms,
                    })
                self._enqueue_checkpoints(a_venir)
                counters = self.state["counters"]
                counters["continuation_signals_started"] = int(
                    counters.get("continuation_signals_started") or 0
                ) + 1
            meta_state[key] = previous
            self.state["metaorder_state"] = meta_state
            self.state["counters"]["continuations"] += 1
            return

        identifier = canonical_metaorder_id(
            vault=vault,
            coin=coin,
            direction=direction,
            signal_ts_ms=received_at_ms,
            first_event_id=event_id,
        )
        meta_state[key] = {
            "direction": direction,
            "last_fill_ts_ms": fill_ts_ms,
            "fill_count": 1,
            "metaorder_id": identifier,
        }
        self.state["metaorder_state"] = meta_state
        self.state["counters"]["metaorders_started"] += 1
        base = {
            "coin": coin,
            "vault": vault,
            "direction": direction,
            "signal_ts_ms": received_at_ms,
            "signal_event_id": event_id,
            "signal_action": entry_action,
            "metaorder_id": identifier,
            "attempts": 0,
        }
        # REFERENCE liée à un carnet DEJA RECU (bloqueur P0 du 16/11), avec repli REST visible.
        a_venir = [{
            **base,
            "stage": "ENTRY",
            "checkpoint_id": f"{identifier}:ENTRY",
            "target_wall_ms": received_at_ms + COPY_DELAY_MS,
        }]
        if not self._emettre_reference_liee(base, signal_received_ms=received_at_ms):
            a_venir.insert(0, {
                **base,
                "stage": "REFERENCE",
                "checkpoint_id": f"{identifier}:REFERENCE",
                "target_wall_ms": received_at_ms,
            })
        self._enqueue_checkpoints(a_venir)

    @staticmethod
    def _exit_checkpoints(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "coin": str(entry["coin"]),
                **{
                    key: entry[key]
                    for key in (
                        "vault",
                        "direction",
                        "signal_ts_ms",
                        "signal_event_id",
                        "signal_action",
                    )
                    if key in entry
                },
                "metaorder_id": str(entry["metaorder_id"]),
                "stage": f"EXIT_{horizon_ms}",
                "checkpoint_id": f"{entry['metaorder_id']}:EXIT:{horizon_ms}",
                "target_wall_ms": int(entry["captured_wall_ms"]) + horizon_ms,
                "attempts": 0,
            }
            for horizon_ms in HORIZONS_MS
        ]

    def _capture_due(self, *, now_ms: int) -> tuple[int, int]:
        captured_ids = list(self.state.get("captured_checkpoint_ids") or [])
        captured_set = set(captured_ids)
        remaining: list[dict[str, Any]] = []
        additions: list[dict[str, Any]] = []
        fetch_cache: dict[str, tuple[int, dict[str, Any] | None]] = {}
        captured_now = 0
        expired_now = 0
        for checkpoint in sorted(
            list(self.state.get("pending") or []),
            key=lambda row: (int(row.get("target_wall_ms") or 0), str(row.get("checkpoint_id") or "")),
        ):
            checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
            target_ms = int(checkpoint.get("target_wall_ms") or 0)
            if not checkpoint_id or checkpoint_id in captured_set:
                continue
            if now_ms < target_ms:
                remaining.append(checkpoint)
                continue
            if now_ms - target_ms > MAX_TARGET_LAG_MS:
                expired_now += 1
                # Le carnet de cette cible n'a jamais ete capture. La periode entre la cible et
                # maintenant est donc sans observation pour ce metaordre : on la declare.
                GAPS.ajouter_fenetre(self.state, GAPS.fenetre(
                    GAPS.TROU_EXPIRATION, debut_ms=target_ms, fin_ms=now_ms))
                continue
            coin = preserve_native_instrument_symbol(checkpoint["coin"])
            cached = fetch_cache.get(coin)
            if cached is None:
                try:
                    raw = self.fetch_book(coin)
                except Exception:  # noqa: BLE001 - collection must remain alive on network errors
                    raw = None
                received_at_ms = self.clock_ms()
                parsed = (
                    _parse_book(raw, received_at_ms=received_at_ms)
                    if isinstance(raw, Mapping)
                    else None
                )
                fetch_cache[coin] = (received_at_ms, parsed)
            else:
                received_at_ms, parsed = cached
            if parsed is None or not (0 <= received_at_ms - target_ms <= MAX_TARGET_LAG_MS):
                checkpoint["attempts"] = int(checkpoint.get("attempts") or 0) + 1
                self.state["counters"]["fetch_retries"] += 1
                remaining.append(checkpoint)
                continue
            row = {
                "schema_version": "hypersmart.copy_vault_l2.v1",
                "instrument_identity_schema": INSTRUMENT_IDENTITY_SCHEMA,
                "coin": preserve_native_instrument_symbol(checkpoint["coin"]),
                **{
                    key: checkpoint[key]
                    for key in (
                        "vault",
                        "direction",
                        "signal_ts_ms",
                        "signal_event_id",
                        "signal_action",
                    )
                    if key in checkpoint
                },
                "received_at_ms": received_at_ms,
                **parsed,
                "source": "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
                "data_origin": "REAL_OBSERVED",
                "causal_observation": True,
                "paper_read_only": True,
                "real_execution": False,
                "checkpoint_stage": str(checkpoint["stage"]),
                "checkpoint_target_ms": target_ms,
                "checkpoint_id": checkpoint_id,
                "metaorder_id": str(checkpoint["metaorder_id"]),
                "collector_protocol": COMPANION_PROTOCOL,
                "writer_run_id": str(self.state["writer_run_id"]),
                "clean_epoch_ms": int(self.state["clean_epoch_ms"]),
            }
            _append_jsonl(self.output_path, row)
            captured_ids.append(checkpoint_id)
            captured_set.add(checkpoint_id)
            captured_now += 1
            if checkpoint.get("stage") == "ENTRY":
                additions.extend(self._exit_checkpoints({
                    **checkpoint,
                    "captured_wall_ms": received_at_ms,
                }))
        self.state["pending"] = remaining
        self._enqueue_checkpoints(additions)
        self.state["captured_checkpoint_ids"] = _trim(captured_ids, MAX_CHECKPOINT_IDS)
        self.state["counters"]["checkpoints_captured"] += captured_now
        self.state["counters"]["checkpoints_expired"] += expired_now
        return captured_now, expired_now

    def _declarer_un_arret(self, now_ms: int) -> None:
        """Arrete, endormi ou bloque plus de MAX_TARGET_LAG_MS, l'ecrivain n'a rien observe.

        17/11/2026 : la veille du PC n'etait visible que par les checkpoints qu'elle faisait
        expirer. Sans checkpoint en attente, aucun trou n'etait declare.
        """
        precedent = self.state.get("updated_at_ms")
        if type(precedent) is not int or precedent <= 0:
            return
        # Un fill recu a l'instant r est encore accepte a cette passe si now - r <= MAX_TARGET_LAG_MS :
        # l'intervalle reellement aveugle est donc ]precedent, now - MAX_TARGET_LAG_MS[. Le debut
        # est decale de la marge de garde pour ne pas avaler les lignes de la passe precedente.
        debut, fin = precedent + GAPS.MARGE_MS + 1, now_ms - MAX_TARGET_LAG_MS
        if fin <= debut:
            return
        counters = self.state["counters"]
        counters["writer_outages"] = int(counters.get("writer_outages") or 0) + 1
        GAPS.ajouter_fenetre(self.state, GAPS.fenetre(GAPS.TROU_ARRET, debut_ms=debut, fin_ms=fin))

    def poll_once(self) -> dict[str, Any]:
        now_ms = self.clock_ms()
        self._declarer_un_arret(now_ms)
        # Le ruban WS d'abord : la liaison de REFERENCE exige un carnet déjà reçu, et l'éligibilité
        # est jugée sur l'horodatage de réception de chaque carnet, pas sur l'ordre de lecture.
        self._lire_carnets_du_ruban()
        rows = self._read_appended_lines()
        for row in rows:
            self._schedule_fill(row, now_ms=now_ms)
        captured, expired = self._capture_due(now_ms=self.clock_ms())
        self.state["updated_at_ms"] = self.clock_ms()
        _atomic_write(self.state_path, self.state)
        counters = dict(self.state.get("counters") or {})
        collector_gap_count = sum(
            int(counters.get(name) or 0)
            for name in (
                "input_rotations",
                "reconnect_backfill_blocked",
                "checkpoints_expired",
                "pending_overflow_rejected",
                "writer_outages",
            )
        )
        return {
            "protocol": COMPANION_PROTOCOL,
            "identity_migration_reset": self.state.get("identity_migration_reset"),
            "lines": len(rows),
            "captured": captured,
            "expired": expired,
            "pending": len(self.state.get("pending") or []),
            "counters": counters,
            "collector_gap_count": collector_gap_count,
            "replay_evidence_complete": collector_gap_count == 0,
            "paper_read_only": True,
            "real_execution": False,
        }


__all__ = [
    "COMPANION_PROTOCOL",
    "CopyVaultCheckpointTail",
    "HORIZONS_MS",
    "INFO_URL",
    "INPUT_RELPATH",
    "MAX_TARGET_LAG_MS",
    "OUTPUT_RELPATH",
    "SCHEMA_VERSION",
    "STATE_RELPATH",
    "coverage_receipt",
    "fetch_hyperliquid_l2_book",
]

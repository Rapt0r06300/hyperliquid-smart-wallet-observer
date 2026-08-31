"""Dedicated typed authority channel for HyperSmart control events.

The channel is deliberately smaller than a generic task runner.  It does not
accept prose, shell fragments or arbitrary targets.  Each event is bound to a
full Git SHA, a source run, a nonce and one predeclared capability.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hl_observer.economics.assumptions import hash_payload

CONTROL_EVENT_SCHEMA = "hypersmart.typed_control_event.v1"
CONTROL_RECEIPT_SCHEMA = "hypersmart.typed_control_receipt.v1"
REPLAY_LEDGER_SCHEMA = "hypersmart.control_event_replay_claim.v1"
MAX_PAYLOAD_BYTES = 32_768
MAX_NESTING_DEPTH = 6
MAX_MAPPING_KEYS = 64
MAX_ARRAY_ITEMS = 100
MAX_STRING_LENGTH = 1_000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

EVENT_POLICIES: dict[str, tuple[str, str]] = {
    "RUN_RESEARCH_JOB": ("autonomous_research_worker", "RUN_PAPER_RESEARCH"),
}

EVENT_FIELDS = frozenset(
    {
        "schema",
        "event_id",
        "event_type",
        "nonce",
        "source_identity",
        "source_run_id",
        "state_version",
        "target",
        "capability",
        "idempotency_key",
        "payload",
    }
)

FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "args",
        "argv",
        "cmd",
        "command",
        "executable",
        "private_key",
        "script",
        "shell",
        "signature",
    }
)


class ControlEventError(ValueError):
    """Typed fail-closed refusal with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _identifier(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not IDENTIFIER_RE.fullmatch(text):
        raise ControlEventError(
            "CONTROL_EVENT_IDENTITY_REFUSED",
            f"{field} doit respecter {IDENTIFIER_RE.pattern}",
        )
    return text


def _bounded_json(value: object, *, path: str = "payload", depth: int = 0) -> Any:
    if depth > MAX_NESTING_DEPTH:
        raise ControlEventError(
            "CONTROL_EVENT_SHAPE_BUDGET_EXCEEDED",
            f"profondeur excessive à {path}",
        )
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ControlEventError(
                "CONTROL_EVENT_TYPE_REFUSED",
                f"nombre non fini à {path}",
            )
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise ControlEventError(
                "CONTROL_EVENT_SHAPE_BUDGET_EXCEEDED",
                f"chaîne trop longue à {path}",
            )
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_MAPPING_KEYS:
            raise ControlEventError(
                "CONTROL_EVENT_SHAPE_BUDGET_EXCEEDED",
                f"trop de champs à {path}",
            )
        normalized: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            if key.casefold() in FORBIDDEN_PAYLOAD_KEYS:
                raise ControlEventError(
                    "ARBITRARY_AUTHORITY_FIELD_REFUSED",
                    f"champ interdit à {path}.{key}",
                )
            normalized[key] = _bounded_json(
                child,
                path=f"{path}.{key}",
                depth=depth + 1,
            )
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        if len(value) > MAX_ARRAY_ITEMS:
            raise ControlEventError(
                "CONTROL_EVENT_SHAPE_BUDGET_EXCEEDED",
                f"tableau trop long à {path}",
            )
        return [
            _bounded_json(child, path=f"{path}[{index}]", depth=depth + 1)
            for index, child in enumerate(value)
        ]
    raise ControlEventError(
        "CONTROL_EVENT_TYPE_REFUSED",
        f"type non JSON à {path}: {type(value).__name__}",
    )


def _canonical_material(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: raw[key]
        for key in sorted(EVENT_FIELDS - {"event_id", "idempotency_key"})
    }


def _idempotency_material(raw: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: str(raw[key])
        for key in (
            "event_type",
            "nonce",
            "source_identity",
            "source_run_id",
            "state_version",
            "target",
            "capability",
        )
    }


def _validate_research_payload(payload: Mapping[str, Any], *, state_version: str) -> None:
    required = {
        "schema",
        "job_id",
        "suite",
        "mode",
        "project_ref",
        "project_sha",
        "paper_only",
        "real_execution",
        "start_live_collection",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ControlEventError(
            "CONTROL_EVENT_PAYLOAD_INCOMPLETE",
            "champs worker absents: " + ", ".join(missing),
        )
    if payload.get("project_ref") != "main":
        raise ControlEventError("CONTROL_EVENT_REF_REFUSED", "project_ref doit être main")
    if str(payload.get("project_sha") or "").lower() != state_version:
        raise ControlEventError(
            "CONTROL_EVENT_STATE_VERSION_MISMATCH",
            "project_sha doit correspondre exactement à state_version",
        )
    if payload.get("paper_only") is not True:
        raise ControlEventError("CONTROL_EVENT_PAPER_REQUIRED", "paper_only doit être true")
    if payload.get("real_execution") is not False:
        raise ControlEventError(
            "CONTROL_EVENT_REAL_EXECUTION_REFUSED",
            "real_execution doit être false",
        )
    if payload.get("start_live_collection") is not False:
        raise ControlEventError(
            "CONTROL_EVENT_LIVE_COLLECTION_REFUSED",
            "start_live_collection doit être false",
        )


@dataclass(frozen=True, slots=True)
class TypedControlEvent:
    event_id: str
    event_type: str
    nonce: str
    source_identity: str
    source_run_id: str
    state_version: str
    target: str
    capability: str
    idempotency_key: str
    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTROL_EVENT_SCHEMA,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "nonce": self.nonce,
            "source_identity": self.source_identity,
            "source_run_id": self.source_run_id,
            "state_version": self.state_version,
            "target": self.target,
            "capability": self.capability,
            "idempotency_key": self.idempotency_key,
            "payload": dict(self.payload),
        }


def validate_typed_control_event(raw: Mapping[str, Any]) -> TypedControlEvent:
    if not isinstance(raw, Mapping):
        raise ControlEventError(
            "PROSE_CONTROL_CHANNEL_REFUSED",
            "l'autorité exige un objet typé, jamais du texte ou du JSON extrait de prose",
        )
    unknown = sorted(str(key) for key in raw if str(key) not in EVENT_FIELDS)
    missing = sorted(EVENT_FIELDS - {str(key) for key in raw})
    if unknown or missing:
        raise ControlEventError(
            "CONTROL_EVENT_SCHEMA_CLOSED",
            f"champs inconnus={unknown}; absents={missing}",
        )
    if raw.get("schema") != CONTROL_EVENT_SCHEMA:
        raise ControlEventError(
            "CONTROL_EVENT_SCHEMA_REFUSED",
            f"schema attendu: {CONTROL_EVENT_SCHEMA}",
        )
    event_type = str(raw.get("event_type") or "")
    policy = EVENT_POLICIES.get(event_type)
    if policy is None:
        raise ControlEventError(
            "CONTROL_EVENT_TYPE_REFUSED",
            f"event_type non allowlisté: {event_type!r}",
        )
    target = _identifier(raw.get("target"), field="target")
    capability = _identifier(raw.get("capability"), field="capability")
    if (target, capability) != policy:
        raise ControlEventError(
            "CONTROL_EVENT_CAPABILITY_REFUSED",
            f"{event_type} exige target={policy[0]} capability={policy[1]}",
        )
    state_version = str(raw.get("state_version") or "").strip().lower()
    if not SHA_RE.fullmatch(state_version):
        raise ControlEventError(
            "CONTROL_EVENT_STATE_VERSION_REFUSED",
            "state_version doit être un SHA Git complet",
        )
    normalized: dict[str, Any] = {
        "schema": CONTROL_EVENT_SCHEMA,
        "event_type": event_type,
        "nonce": _identifier(raw.get("nonce"), field="nonce"),
        "source_identity": _identifier(
            raw.get("source_identity"), field="source_identity"
        ),
        "source_run_id": _identifier(raw.get("source_run_id"), field="source_run_id"),
        "state_version": state_version,
        "target": target,
        "capability": capability,
        "payload": _bounded_json(raw.get("payload")),
    }
    payload = normalized["payload"]
    if not isinstance(payload, Mapping):
        raise ControlEventError(
            "CONTROL_EVENT_PAYLOAD_REFUSED",
            "payload doit être un objet JSON borné",
        )
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ControlEventError(
            "CONTROL_EVENT_SHAPE_BUDGET_EXCEEDED",
            f"payload={len(encoded)} octets > {MAX_PAYLOAD_BYTES}",
        )
    _validate_research_payload(payload, state_version=state_version)
    expected_idempotency = hash_payload(_idempotency_material(normalized))
    if str(raw.get("idempotency_key") or "") != expected_idempotency:
        raise ControlEventError(
            "CONTROL_EVENT_IDEMPOTENCY_MISMATCH",
            "idempotency_key ne correspond pas au contrat",
        )
    normalized["idempotency_key"] = expected_idempotency
    expected_event_id = hash_payload(_canonical_material(normalized))
    if str(raw.get("event_id") or "") != expected_event_id:
        raise ControlEventError(
            "CONTROL_EVENT_DIGEST_MISMATCH",
            "event_id ne correspond pas au contenu canonique",
        )
    return TypedControlEvent(
        event_id=expected_event_id,
        event_type=event_type,
        nonce=normalized["nonce"],
        source_identity=normalized["source_identity"],
        source_run_id=normalized["source_run_id"],
        state_version=state_version,
        target=target,
        capability=capability,
        idempotency_key=expected_idempotency,
        payload=payload,
    )


def build_typed_control_event(
    *,
    event_type: str,
    nonce: str,
    source_identity: str,
    source_run_id: str,
    state_version: str,
    target: str,
    capability: str,
    payload: Mapping[str, Any],
) -> TypedControlEvent:
    bounded_payload = _bounded_json(payload)
    if not isinstance(bounded_payload, Mapping):
        raise ControlEventError(
            "CONTROL_EVENT_PAYLOAD_REFUSED",
            "payload doit être un objet JSON borné",
        )
    raw: dict[str, Any] = {
        "schema": CONTROL_EVENT_SCHEMA,
        "event_id": "",
        "event_type": event_type,
        "nonce": nonce,
        "source_identity": source_identity,
        "source_run_id": source_run_id,
        "state_version": str(state_version).lower(),
        "target": target,
        "capability": capability,
        "idempotency_key": "",
        "payload": dict(bounded_payload),
    }
    raw["idempotency_key"] = hash_payload(_idempotency_material(raw))
    raw["event_id"] = hash_payload(_canonical_material(raw))
    return validate_typed_control_event(raw)


def control_event_receipt(
    event: TypedControlEvent,
    *,
    decision: str,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "schema": CONTROL_RECEIPT_SCHEMA,
        "decision": decision,
        "event_id": event.event_id,
        "idempotency_key": event.idempotency_key,
        "event_type": event.event_type,
        "source_identity": event.source_identity,
        "source_run_id": event.source_run_id,
        "state_version": event.state_version,
        "target": event.target,
        "capability": event.capability,
        "paper_only": event.payload.get("paper_only") is True,
        "real_execution": event.payload.get("real_execution") is True,
        "ledger_path": str(ledger_path) if ledger_path is not None else None,
    }


class ControlEventReplayLedger:
    """Append-only idempotency claims for accepted control events."""

    def __init__(self, path: Path, *, lock_timeout_seconds: float = 3.0) -> None:
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.lock_timeout_seconds = max(0.1, float(lock_timeout_seconds))

    def _acquire(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                return os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ControlEventError(
                        "CONTROL_EVENT_LEDGER_BUSY",
                        f"verrou indisponible: {self.lock_path}",
                    ) from None
                time.sleep(0.02)

    def _claims(self) -> dict[str, str]:
        claims: dict[str, str] = {}
        if not self.path.exists():
            return claims
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ControlEventError(
                "CONTROL_EVENT_LEDGER_UNREADABLE", str(exc)
            ) from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ControlEventError(
                    "CONTROL_EVENT_LEDGER_CORRUPT",
                    f"ligne {line_number}: {exc.msg}",
                ) from exc
            if not isinstance(row, dict) or row.get("schema") != REPLAY_LEDGER_SCHEMA:
                raise ControlEventError(
                    "CONTROL_EVENT_LEDGER_CORRUPT",
                    f"ligne {line_number}: schéma invalide",
                )
            key = str(row.get("idempotency_key") or "")
            event_id = str(row.get("event_id") or "")
            if not DIGEST_RE.fullmatch(key) or not DIGEST_RE.fullmatch(event_id):
                raise ControlEventError(
                    "CONTROL_EVENT_LEDGER_CORRUPT",
                    f"ligne {line_number}: digest invalide",
                )
            claims[key] = event_id
        return claims

    def claim(self, event: TypedControlEvent) -> dict[str, Any]:
        descriptor = self._acquire()
        os.close(descriptor)
        try:
            claims = self._claims()
            previous = claims.get(event.idempotency_key)
            if previous is not None:
                raise ControlEventError(
                    "CONTROL_EVENT_REPLAY_REFUSED",
                    f"nonce/source/state déjà consommé par event_id={previous}",
                )
            row = {
                "schema": REPLAY_LEDGER_SCHEMA,
                "claimed_at": datetime.now(UTC).isoformat(),
                "event_id": event.event_id,
                "idempotency_key": event.idempotency_key,
                "source_identity": event.source_identity,
                "source_run_id": event.source_run_id,
                "state_version": event.state_version,
                "target": event.target,
                "capability": event.capability,
            }
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        row,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            self.lock_path.unlink(missing_ok=True)
        return control_event_receipt(
            event,
            decision="ACCEPTED_AND_CLAIMED",
            ledger_path=self.path,
        )


__all__ = [
    "CONTROL_EVENT_SCHEMA",
    "CONTROL_RECEIPT_SCHEMA",
    "EVENT_POLICIES",
    "ControlEventError",
    "ControlEventReplayLedger",
    "TypedControlEvent",
    "build_typed_control_event",
    "control_event_receipt",
    "validate_typed_control_event",
]

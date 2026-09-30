"""Capability air gap for externally controlled text.

Raw text is immutable content-addressed data.  A read-only projector can emit
only bounded scalar facts with exact character spans.  The trusted writer
accepts those validated projections or evidence references, never raw text.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.datasets.dataset_untrusted_guard import validate_relative_member
from hl_observer.economics.assumptions import hash_payload

SOURCE_REF_SCHEMA = "hypersmart.content_addressed_source_ref.v1"
PROJECTION_SCHEMA = "hypersmart.bounded_source_projection.v1"
EVIDENCE_REF_SCHEMA = "hypersmart.projection_evidence_ref.v1"
WRITER_ROW_SCHEMA = "hypersmart.trusted_projection_writer_row.v1"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_FACTS = 64
MAX_FACT_STRING = 1_000
MAX_ORIGIN_LENGTH = 2_048
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,95}$")
FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {"args", "argv", "capability", "cmd", "command", "event", "script", "shell", "target"}
)


class ProjectionAirGapError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _digest(value: object, *, field: str) -> str:
    text = str(value or "").lower()
    if not DIGEST_RE.fullmatch(text):
        raise ProjectionAirGapError("PROJECTION_DIGEST_INVALID", f"{field} invalide")
    return text


def _bounded_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProjectionAirGapError(
                "PROJECTION_VALUE_INVALID", "nombre non fini"
            )
        return value
    if isinstance(value, str):
        if len(value) > MAX_FACT_STRING:
            raise ProjectionAirGapError(
                "PROJECTION_OUTPUT_BUDGET_EXCEEDED",
                f"chaîne de fait > {MAX_FACT_STRING} caractères",
            )
        return value
    raise ProjectionAirGapError(
        "PROJECTION_VALUE_INVALID",
        f"seuls les scalaires JSON sont admis, reçu={type(value).__name__}",
    )


@dataclass(frozen=True, slots=True)
class ContentAddressedSourceRef:
    source_hash: str
    member: str
    byte_length: int
    media_type: str
    origin_locator: str
    license_class: str
    redistribution: str

    def __post_init__(self) -> None:
        _digest(self.source_hash, field="source_hash")
        validate_relative_member(self.member)
        expected = f"sha256/{self.source_hash[:2]}/{self.source_hash}.txt"
        if self.member != expected:
            raise ProjectionAirGapError(
                "SOURCE_ADDRESS_MISMATCH", f"member attendu={expected}"
            )
        if self.byte_length < 0 or self.byte_length > MAX_SOURCE_BYTES:
            raise ProjectionAirGapError(
                "SOURCE_SIZE_REFUSED", f"byte_length={self.byte_length}"
            )
        if not self.media_type or len(self.media_type) > 120:
            raise ProjectionAirGapError("SOURCE_MEDIA_TYPE_INVALID", self.media_type)
        if not self.origin_locator or len(self.origin_locator) > MAX_ORIGIN_LENGTH:
            raise ProjectionAirGapError(
                "SOURCE_ORIGIN_INVALID", "origin_locator absent ou trop long"
            )
        if (
            not self.license_class
            or len(self.license_class) > 120
            or not self.redistribution
            or len(self.redistribution) > 120
        ):
            raise ProjectionAirGapError(
                "SOURCE_ENTITLEMENT_INCOMPLETE",
                "license_class et redistribution sont obligatoires",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SOURCE_REF_SCHEMA,
            "source_hash": self.source_hash,
            "member": self.member,
            "byte_length": self.byte_length,
            "media_type": self.media_type,
            "origin_locator": self.origin_locator,
            "license_class": self.license_class,
            "redistribution": self.redistribution,
        }


class ContentAddressedSourceStore:
    """Immutable raw-source ingestion, separate from canonical writers."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def ingest_text(
        self,
        text: str,
        *,
        origin_locator: str,
        media_type: str = "text/plain",
        license_class: str = "UNKNOWN_REQUIRES_REVIEW",
        redistribution: str = "NO_REDISTRIBUTION",
    ) -> ContentAddressedSourceRef:
        if not isinstance(text, str):
            raise ProjectionAirGapError("RAW_SOURCE_TYPE_REFUSED", "texte requis")
        payload = text.encode("utf-8")
        if len(payload) > MAX_SOURCE_BYTES:
            raise ProjectionAirGapError(
                "SOURCE_SIZE_REFUSED", f"source={len(payload)} octets"
            )
        digest = _digest_bytes(payload)
        member = f"sha256/{digest[:2]}/{digest}.txt"
        ref = ContentAddressedSourceRef(
            source_hash=digest,
            member=member,
            byte_length=len(payload),
            media_type=media_type,
            origin_locator=origin_locator,
            license_class=license_class,
            redistribution=redistribution,
        )
        target = self.root / Path(member)
        resolved_target = target.resolve(strict=False)
        try:
            resolved_target.relative_to(self.root)
        except ValueError as exc:
            raise ProjectionAirGapError(
                "RAW_SOURCE_PATH_REFUSED", str(resolved_target)
            ) from exc
        target = resolved_target
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if _digest_bytes(target.read_bytes()) != digest:
                raise ProjectionAirGapError(
                    "CONTENT_ADDRESS_COLLISION", f"contenu divergent: {target}"
                )
            return ref
        temporary = target.with_suffix(f".tmp-{os.getpid()}")
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return ref


@dataclass(frozen=True, slots=True)
class RawExternalDocument:
    source: ContentAddressedSourceRef
    text: str

    def __repr__(self) -> str:
        return (
            "RawExternalDocument(source_hash="
            f"{self.source.source_hash!r}, chars={len(self.text)})"
        )


@dataclass(frozen=True, slots=True)
class ProjectionFact:
    fact_id: str
    field: str
    value: str | int | float | bool | None
    span_start: int
    span_end: int
    span_sha256: str
    source_pointer: str

    def validate(self, source: ContentAddressedSourceRef) -> None:
        _digest(self.fact_id, field="fact_id")
        _digest(self.span_sha256, field="span_sha256")
        if (
            not FIELD_RE.fullmatch(self.field)
            or self.field.casefold() in FORBIDDEN_AUTHORITY_FIELDS
        ):
            raise ProjectionAirGapError(
                "PROJECTION_FIELD_REFUSED", f"field={self.field!r}"
            )
        _bounded_scalar(self.value)
        if self.span_start < 0 or self.span_end <= self.span_start:
            raise ProjectionAirGapError(
                "PROJECTION_SPAN_INVALID",
                f"span={self.span_start}:{self.span_end}",
            )
        expected_pointer = (
            f"cas:{source.source_hash}#chars={self.span_start}:{self.span_end}"
        )
        if self.source_pointer != expected_pointer:
            raise ProjectionAirGapError(
                "PROJECTION_POINTER_MISMATCH", self.source_pointer
            )
        expected_fact_id = hash_payload(
            {
                "source_hash": source.source_hash,
                "field": self.field,
                "value": self.value,
                "span_start": self.span_start,
                "span_end": self.span_end,
                "span_sha256": self.span_sha256,
            }
        )
        if self.fact_id != expected_fact_id:
            raise ProjectionAirGapError(
                "PROJECTION_FACT_DIGEST_MISMATCH", self.fact_id
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "field": self.field,
            "value": self.value,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "span_sha256": self.span_sha256,
            "source_pointer": self.source_pointer,
        }


@dataclass(frozen=True, slots=True)
class BoundedSourceProjection:
    source: ContentAddressedSourceRef
    parser_version: str
    projection_version: str
    facts: tuple[ProjectionFact, ...]
    projection_hash: str

    def material(self) -> dict[str, Any]:
        return {
            "schema": PROJECTION_SCHEMA,
            "source": self.source.as_dict(),
            "parser_version": self.parser_version,
            "projection_version": self.projection_version,
            "facts": [fact.as_dict() for fact in self.facts],
        }

    def validate(self) -> None:
        self.source.__post_init__()
        if not self.parser_version or len(self.parser_version) > 120:
            raise ProjectionAirGapError(
                "PROJECTION_VERSION_INVALID", "parser_version invalide"
            )
        if not self.projection_version or len(self.projection_version) > 120:
            raise ProjectionAirGapError(
                "PROJECTION_VERSION_INVALID", "projection_version invalide"
            )
        if not self.facts or len(self.facts) > MAX_FACTS:
            raise ProjectionAirGapError(
                "PROJECTION_OUTPUT_BUDGET_EXCEEDED", f"facts={len(self.facts)}"
            )
        for fact in self.facts:
            fact.validate(self.source)
        expected = hash_payload(self.material())
        if self.projection_hash != expected:
            raise ProjectionAirGapError(
                "PROJECTION_DIGEST_MISMATCH", "projection_hash invalide"
            )

    def as_dict(self) -> dict[str, Any]:
        return {**self.material(), "projection_hash": self.projection_hash}


class ReadOnlyUntrustedProjector:
    """Reads immutable CAS objects and emits bounded projections only."""

    def __init__(self, store_root: Path | str) -> None:
        self.store_root = Path(store_root).resolve()

    def read(self, source: ContentAddressedSourceRef) -> RawExternalDocument:
        source.__post_init__()
        path = (self.store_root / Path(source.member)).resolve()
        try:
            path.relative_to(self.store_root)
        except ValueError as exc:
            raise ProjectionAirGapError(
                "RAW_SOURCE_PATH_REFUSED", str(path)
            ) from exc
        if path.is_symlink() or not path.is_file():
            raise ProjectionAirGapError("RAW_SOURCE_MISSING", str(path))
        payload = path.read_bytes()
        if len(payload) != source.byte_length or _digest_bytes(payload) != source.source_hash:
            raise ProjectionAirGapError(
                "RAW_SOURCE_INTEGRITY_FAILED", source.source_hash
            )
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectionAirGapError("RAW_SOURCE_ENCODING_REFUSED", "UTF-8 requis") from exc
        return RawExternalDocument(source=source, text=text)

    def project(
        self,
        document: RawExternalDocument,
        records: Sequence[Mapping[str, Any]],
        *,
        parser_version: str,
        projection_version: str,
    ) -> BoundedSourceProjection:
        if not isinstance(document, RawExternalDocument):
            raise ProjectionAirGapError(
                "RAW_SOURCE_HANDLE_REQUIRED", "document lu par le projecteur requis"
            )
        if not records or len(records) > MAX_FACTS:
            raise ProjectionAirGapError(
                "PROJECTION_OUTPUT_BUDGET_EXCEEDED", f"records={len(records)}"
            )
        facts: list[ProjectionFact] = []
        seen: set[str] = set()
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise ProjectionAirGapError(
                    "PROJECTION_RECORD_INVALID", f"record[{index}] n'est pas un objet"
                )
            if set(record) != {"field", "value", "span_start", "span_end"}:
                raise ProjectionAirGapError(
                    "PROJECTION_RECORD_SCHEMA_CLOSED", f"record[{index}]"
                )
            field = str(record["field"])
            if not FIELD_RE.fullmatch(field) or field.casefold() in FORBIDDEN_AUTHORITY_FIELDS:
                raise ProjectionAirGapError(
                    "PROJECTION_FIELD_REFUSED", f"field={field!r}"
                )
            value = _bounded_scalar(record["value"])
            start = int(record["span_start"])
            end = int(record["span_end"])
            if start < 0 or end <= start or end > len(document.text):
                raise ProjectionAirGapError(
                    "PROJECTION_SPAN_INVALID", f"span={start}:{end}"
                )
            span_hash = _digest_bytes(document.text[start:end].encode("utf-8"))
            pointer = f"cas:{document.source.source_hash}#chars={start}:{end}"
            fact_material = {
                "source_hash": document.source.source_hash,
                "field": field,
                "value": value,
                "span_start": start,
                "span_end": end,
                "span_sha256": span_hash,
            }
            fact_id = hash_payload(fact_material)
            if fact_id in seen:
                raise ProjectionAirGapError(
                    "PROJECTION_DUPLICATE_FACT", f"record[{index}]"
                )
            seen.add(fact_id)
            facts.append(
                ProjectionFact(
                    fact_id=fact_id,
                    field=field,
                    value=value,
                    span_start=start,
                    span_end=end,
                    span_sha256=span_hash,
                    source_pointer=pointer,
                )
            )
        provisional = BoundedSourceProjection(
            source=document.source,
            parser_version=str(parser_version),
            projection_version=str(projection_version),
            facts=tuple(facts),
            projection_hash="",
        )
        projection = BoundedSourceProjection(
            source=document.source,
            parser_version=provisional.parser_version,
            projection_version=provisional.projection_version,
            facts=provisional.facts,
            projection_hash=hash_payload(provisional.material()),
        )
        projection.validate()
        return projection


@dataclass(frozen=True, slots=True)
class ValidatedProjectionEvidenceRef:
    projection_hash: str
    source_hash: str
    fact_ids: tuple[str, ...]

    @classmethod
    def from_projection(
        cls, projection: BoundedSourceProjection
    ) -> ValidatedProjectionEvidenceRef:
        projection.validate()
        return cls(
            projection_hash=projection.projection_hash,
            source_hash=projection.source.source_hash,
            fact_ids=tuple(fact.fact_id for fact in projection.facts),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": EVIDENCE_REF_SCHEMA,
            "projection_hash": _digest(self.projection_hash, field="projection_hash"),
            "source_hash": _digest(self.source_hash, field="source_hash"),
            "fact_ids": [_digest(fact_id, field="fact_id") for fact_id in self.fact_ids],
        }


class TrustedProjectionWriter:
    """Canonical writer with no API accepting raw external source text."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append_projection(self, projection: BoundedSourceProjection) -> dict[str, Any]:
        if not isinstance(projection, BoundedSourceProjection):
            raise ProjectionAirGapError(
                "RAW_SOURCE_TO_WRITER_REFUSED",
                "le writer accepte uniquement BoundedSourceProjection",
            )
        projection.validate()
        evidence_ref = ValidatedProjectionEvidenceRef.from_projection(projection)
        row = {
            "schema": WRITER_ROW_SCHEMA,
            "kind": "VALIDATED_PROJECTION",
            "projection": projection.as_dict(),
            "evidence_ref": evidence_ref.as_dict(),
            "raw_source_embedded": False,
            "paper_only": True,
            "real_execution": False,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        return row

    def append_evidence_ref(
        self, evidence_ref: ValidatedProjectionEvidenceRef
    ) -> dict[str, Any]:
        if not isinstance(evidence_ref, ValidatedProjectionEvidenceRef):
            raise ProjectionAirGapError(
                "RAW_SOURCE_TO_WRITER_REFUSED",
                "le writer accepte uniquement une référence d'évidence validée",
            )
        row = {
            "schema": WRITER_ROW_SCHEMA,
            "kind": "VALIDATED_EVIDENCE_REFERENCE",
            "evidence_ref": evidence_ref.as_dict(),
            "raw_source_embedded": False,
            "paper_only": True,
            "real_execution": False,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        return row


__all__ = [
    "BoundedSourceProjection",
    "ContentAddressedSourceRef",
    "ContentAddressedSourceStore",
    "ProjectionAirGapError",
    "ProjectionFact",
    "RawExternalDocument",
    "ReadOnlyUntrustedProjector",
    "TrustedProjectionWriter",
    "ValidatedProjectionEvidenceRef",
]

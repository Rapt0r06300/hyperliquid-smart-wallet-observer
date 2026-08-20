"""Invariants pre-run AUD-261 -> AUD-300.

These helpers close the data-mesh, provenance, persistence and recovery gaps
without enabling any real trading capability.  They are intentionally
fail-closed: missing metadata is an error, never an inferred zero/default.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

STRONG_PROVENANCE = frozenset({"MEASURED", "RECORDED", "EXCHANGE_RAW"})
PRICE_SEMANTICS = frozenset({"mark", "index", "oracle", "last_trade"})
MARKET_EVENT_TYPES = frozenset({"trade", "book", "funding"})
CHECKPOINT_REQUIRED = frozenset({
    "schema_version",
    "run_id",
    "phase",
    "family_state",
    "search_state",
    "seed",
    "counters",
    "data_fingerprint",
})


class PreRunInvariantError(ValueError):
    """Fail-closed error for an AUD-261..300 invariant violation."""


def _positive_number(value: Any, *, name: str, allow_zero: bool = False) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PreRunInvariantError(f"{name}_MISSING_OR_INVALID") from exc
    if (out < 0) if allow_zero else (out <= 0):
        raise PreRunInvariantError(f"{name}_OUT_OF_RANGE")
    return out


def stable_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# AUD-261/262 -----------------------------------------------------------------
def construire_catalogue_signaux(specs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build an authoritative signal catalogue; duplicate/anonymous signals are forbidden."""
    catalogue: dict[str, dict[str, Any]] = {}
    for raw in specs:
        spec = dict(raw)
        name = str(spec.get("name") or "").strip()
        if not name:
            raise PreRunInvariantError("SIGNAL_NAME_MISSING")
        if name in catalogue:
            raise PreRunInvariantError(f"DUPLICATE_SIGNAL:{name}")
        for field in ("family", "inputs", "version"):
            if not spec.get(field):
                raise PreRunInvariantError(f"SIGNAL_{field.upper()}_MISSING:{name}")
        catalogue[name] = spec
    return catalogue


def verifier_signaux_utilises(catalogue: Mapping[str, Any], used_names: Iterable[str]) -> dict[str, Any]:
    used = tuple(str(x) for x in used_names)
    unknown = sorted({name for name in used if name not in catalogue})
    return {"ok": not unknown, "unknown": unknown, "reason": None if not unknown else "UNKNOWN_SIGNAL_USED"}


# AUD-263/264 -----------------------------------------------------------------
def construire_lineage_ledger(
    *,
    source: str,
    raw_fingerprint: str,
    normalizer: str,
    feature: str,
    signal: str,
    intent_id: str,
    fill_id: str,
    ledger_entry_id: str,
    provenance: str,
) -> dict[str, str]:
    fields = {
        "source": source,
        "raw_fingerprint": raw_fingerprint,
        "normalizer": normalizer,
        "feature": feature,
        "signal": signal,
        "intent_id": intent_id,
        "fill_id": fill_id,
        "ledger_entry_id": ledger_entry_id,
        "provenance": provenance,
    }
    missing = [k for k, v in fields.items() if not str(v).strip()]
    if missing:
        raise PreRunInvariantError("LINEAGE_MISSING:" + ",".join(missing))
    return fields


def verifier_provenance_forte(record: Mapping[str, Any]) -> dict[str, Any]:
    provenance = str(record.get("provenance") or "").upper()
    required = ("source", "raw_fingerprint", "normalizer")
    missing = [x for x in required if not record.get(x)]
    ok = provenance in STRONG_PROVENANCE and not missing
    return {
        "ok": ok,
        "provenance": provenance or "UNKNOWN",
        "missing": missing,
        "reason": None if ok else "WEAK_PROVENANCE_USED",
    }


# AUD-265/266 -----------------------------------------------------------------
def construire_symbol_master(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Canonical venue/symbol metadata. No implicit quantity unit or multiplier."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        venue = str(row.get("venue") or "").upper()
        symbol = str(row.get("symbol") or "").upper()
        if not venue or not symbol:
            raise PreRunInvariantError("SYMBOL_ID_MISSING")
        for field in ("base", "quote", "tick_size", "lot_size", "contract_multiplier", "quantity_unit"):
            if row.get(field) in (None, ""):
                raise PreRunInvariantError(f"SYMBOL_METADATA_MISSING:{venue}:{symbol}:{field}")
        _positive_number(row["tick_size"], name="tick_size")
        _positive_number(row["lot_size"], name="lot_size")
        _positive_number(row["contract_multiplier"], name="contract_multiplier")
        quantity_unit = str(row["quantity_unit"]).lower()
        if quantity_unit not in {"base", "contract"}:
            raise PreRunInvariantError(f"UNSUPPORTED_QUANTITY_UNIT:{quantity_unit}")
        key = (venue, symbol)
        if key in out:
            raise PreRunInvariantError(f"DUPLICATE_SYMBOL:{venue}:{symbol}")
        row["venue"], row["symbol"], row["quantity_unit"] = venue, symbol, quantity_unit
        out[key] = row
    return out


def calculer_notional_quote(*, price: float, quantity: float, metadata: Mapping[str, Any]) -> float:
    px = _positive_number(price, name="price")
    qty = _positive_number(quantity, name="quantity")
    unit = str(metadata.get("quantity_unit") or "").lower()
    if unit == "base":
        multiplier = 1.0
    elif unit == "contract":
        multiplier = _positive_number(metadata.get("contract_multiplier"), name="contract_multiplier")
    else:
        raise PreRunInvariantError("UNIT_MISMATCH_OR_UNKNOWN")
    return px * qty * multiplier


# AUD-267/268 -----------------------------------------------------------------
def valider_fee_schedule(schedule: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(schedule)
    for field in ("venue", "version", "source", "effective_from_ms", "maker_bps", "taker_bps"):
        if row.get(field) in (None, ""):
            raise PreRunInvariantError(f"FEE_SCHEDULE_MISSING:{field}")
    for field in ("maker_bps", "taker_bps"):
        row[field] = _positive_number(row[field], name=field, allow_zero=True)
    row["effective_from_ms"] = int(row["effective_from_ms"])
    return row


def cout_cross_venue_bps(
    *,
    entry_fee_bps: float,
    exit_fee_bps: float,
    spread_bps: float,
    slippage_bps: float,
    transfer_bps: float,
    rebalance_bps: float,
) -> float:
    components = {
        "entry_fee_bps": entry_fee_bps,
        "exit_fee_bps": exit_fee_bps,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "transfer_bps": transfer_bps,
        "rebalance_bps": rebalance_bps,
    }
    vals = [_positive_number(v, name=k, allow_zero=True) for k, v in components.items()]
    return sum(vals)


# AUD-269/270 -----------------------------------------------------------------
_TS_FACTORS = {"s": 1000, "ms": 1, "us": 1 / 1000, "ns": 1 / 1_000_000}


def canonicaliser_timestamp_ms(value: int | float, *, unit: str) -> int:
    if unit not in _TS_FACTORS:
        raise PreRunInvariantError("TIMESTAMP_UNIT_REQUIRED")
    try:
        out = float(value) * _TS_FACTORS[unit]
    except (TypeError, ValueError) as exc:
        raise PreRunInvariantError("TIMESTAMP_INVALID") from exc
    if out < 0:
        raise PreRunInvariantError("TIMESTAMP_NEGATIVE")
    return int(round(out))


def verifier_drift_lead_lag(*, source_ts_ms: int, target_ts_ms: int, max_clock_drift_ms: int) -> dict[str, Any]:
    limit = int(max_clock_drift_ms)
    if limit < 0:
        raise PreRunInvariantError("CLOCK_DRIFT_LIMIT_INVALID")
    drift = abs(int(target_ts_ms) - int(source_ts_ms))
    ok = drift <= limit
    return {"ok": ok, "drift_ms": drift, "reason": None if ok else "INTERVENUE_CLOCK_DRIFT"}


# AUD-271/272/273 --------------------------------------------------------------
def normaliser_evenement_marche(event: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(event)
    kind = str(row.get("type") or "").lower()
    if kind not in MARKET_EVENT_TYPES:
        raise PreRunInvariantError("MARKET_EVENT_TYPE_UNKNOWN")
    for field in ("venue", "symbol", "ts_ms"):
        if row.get(field) in (None, ""):
            raise PreRunInvariantError(f"MARKET_EVENT_MISSING:{field}")
    row["venue"] = str(row["venue"]).upper()
    row["symbol"] = str(row["symbol"]).upper()
    row["ts_ms"] = int(row["ts_ms"])
    if kind == "trade":
        for field in ("price", "size", "side"):
            if row.get(field) in (None, ""):
                raise PreRunInvariantError(f"TRADE_MISSING:{field}")
    elif kind == "book":
        for field in ("bids", "asks", "depth"):
            if row.get(field) in (None, ""):
                raise PreRunInvariantError(f"BOOK_MISSING:{field}")
    else:
        for field in ("rate", "interval_ms"):
            if row.get(field) in (None, ""):
                raise PreRunInvariantError(f"FUNDING_MISSING:{field}")
    return row


def comparer_staleness_intervenue(events: Sequence[Mapping[str, Any]], *, now_ms: int, max_age_ms: int) -> dict[str, Any]:
    ages = {str(e.get("venue") or "UNKNOWN").upper(): int(now_ms) - int(e["ts_ms"]) for e in events}
    stale = sorted(v for v, age in ages.items() if age < 0 or age > int(max_age_ms))
    return {"ok": not stale, "ages_ms": ages, "stale_venues": stale, "reason": None if not stale else "STALE_INTERVENUE_DATA"}


def lire_prix_semantique(event: Mapping[str, Any], *, semantic: str) -> float:
    semantic = semantic.lower()
    if semantic not in PRICE_SEMANTICS:
        raise PreRunInvariantError("PRICE_SEMANTIC_UNKNOWN")
    if semantic not in event or event.get(semantic) is None:
        raise PreRunInvariantError(f"PRICE_SEMANTIC_MISSING:{semantic}")
    return _positive_number(event[semantic], name=semantic)


# AUD-274..278 ----------------------------------------------------------------
def construire_evidence_bundle(*, lineage: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    provenance = verifier_provenance_forte(lineage)
    return {
        "level": "STRONG" if provenance["ok"] else "WEAK",
        "provenance": provenance,
        "lineage_fingerprint": stable_fingerprint(dict(lineage)),
        "payload_fingerprint": stable_fingerprint(dict(payload)),
    }


def shadow_record_brut(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(event)
    return {"raw": raw, "raw_fingerprint": stable_fingerprint(raw), "recorded_at_ns": time.time_ns()}


def replay_deterministe(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(e) for e in events]
    for row in rows:
        if row.get("ts_ms") is None or not row.get("venue"):
            raise PreRunInvariantError("REPLAY_EVENT_MISSING_ORDER_KEY")
    return sorted(rows, key=lambda r: (int(r["ts_ms"]), str(r["venue"]), int(r.get("sequence", 0)), stable_fingerprint(r)))


def valider_data_contract(event: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    missing = sorted(field for field in required_fields if event.get(field) in (None, ""))
    return {"ok": not missing, "missing": missing, "reason": None if not missing else "DATA_CONTRACT_MISSING_FIELDS"}


def valider_book_granularity(metadata: Mapping[str, Any]) -> dict[str, Any]:
    required = ("venue", "depth_levels", "snapshot_interval_ms", "update_mode")
    missing = [x for x in required if metadata.get(x) in (None, "")]
    ok = not missing and int(metadata["depth_levels"]) > 0 and int(metadata["snapshot_interval_ms"]) > 0
    return {"ok": ok, "missing": missing, "reason": None if ok else "BOOK_GRANULARITY_UNDOCUMENTED"}


# AUD-279/280 -----------------------------------------------------------------
def cle_dedup_coinbase(event: Mapping[str, Any]) -> tuple[str, str, str]:
    product = str(event.get("product_id") or "").upper()
    trade_id = str(event.get("trade_id") or "")
    if not product or not trade_id:
        raise PreRunInvariantError("COINBASE_DEDUP_KEY_INCOMPLETE")
    return ("COINBASE", product, trade_id)


def avancer_cursor_idempotent(*, current: int | None, observed: int) -> int:
    obs = int(observed)
    if current is None:
        return obs
    cur = int(current)
    if obs < cur:
        raise PreRunInvariantError("CURSOR_REGRESSION")
    return max(cur, obs)


# AUD-281..285 ----------------------------------------------------------------
def configurer_sqlite_strict(conn: sqlite3.Connection, *, busy_timeout_ms: int = 10_000) -> dict[str, Any]:
    if busy_timeout_ms <= 0:
        raise PreRunInvariantError("SQLITE_BUSY_TIMEOUT_INVALID")
    mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")
    fk = int(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    sync = int(conn.execute("PRAGMA synchronous").fetchone()[0])
    if mode != "wal" or fk != 1 or sync < 2:
        raise PreRunInvariantError("SQLITE_STRICT_POLICY_NOT_APPLIED")
    return {"journal_mode": mode, "busy_timeout_ms": int(busy_timeout_ms), "foreign_keys": fk, "synchronous": sync}


def transaction_sqlite_atomique(conn: sqlite3.Connection, statements: Sequence[tuple[str, Sequence[Any]]]) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
        for sql, params in statements:
            conn.execute(sql, tuple(params))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def valider_schema_version(manifest: Mapping[str, Any], *, expected: int) -> dict[str, Any]:
    actual = manifest.get("schema_version")
    ok = isinstance(actual, int) and actual == int(expected)
    return {"ok": ok, "actual": actual, "expected": int(expected), "reason": None if ok else "SCHEMA_VERSION_MISMATCH"}


def valider_retention_reproductible(policy: Mapping[str, Any]) -> dict[str, Any]:
    required_true = ("keeps_raw", "keeps_normalized", "keeps_lineage", "keeps_schema_version")
    missing = [x for x in required_true if policy.get(x) is not True]
    return {"ok": not missing, "missing": missing, "reason": None if not missing else "RETENTION_BREAKS_REPLAY"}


def valider_archive_auditable(sample: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    missing = [x for x in required_fields if x not in sample]
    return {"ok": not missing, "missing": missing, "reason": None if not missing else "ARCHIVE_DROPPED_AUDIT_FIELDS"}


# AUD-286..291 ----------------------------------------------------------------
def nouveau_run_context(run_id: str | None = None) -> dict[str, str]:
    rid = str(run_id or uuid.uuid4())
    try:
        uuid.UUID(rid)
    except ValueError as exc:
        raise PreRunInvariantError("RUN_ID_NOT_UUID") from exc
    return {"run_id": rid}


def verifier_run_id_commun(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = {str(r.get("run_id") or "") for r in records}
    ids.discard("")
    ok = len(ids) == 1 and all(r.get("run_id") for r in records)
    return {"ok": ok, "run_ids": sorted(ids), "reason": None if ok else "RUN_ID_NOT_COMMON"}


def correlation_id(*, run_id: str, process: str, local_event_id: str) -> str:
    if not run_id or not process or not local_event_id:
        raise PreRunInvariantError("CORRELATION_INPUT_MISSING")
    return stable_fingerprint([run_id, process, local_event_id])[:32]


def log_structure(*, level: str, event: str, run_id: str, process: str, fields: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not all((level, event, run_id, process)):
        raise PreRunInvariantError("STRUCTURED_LOG_REQUIRED_FIELD_MISSING")
    return {
        "ts_ns": time.time_ns(),
        "level": level.upper(),
        "event": event,
        "run_id": run_id,
        "process": process,
        "fields": dict(fields or {}),
    }


def agreger_sante_collecteurs(statuses: Mapping[str, str], required_collectors: Sequence[str]) -> dict[str, Any]:
    bad: dict[str, str] = {}
    for collector in required_collectors:
        state = str(statuses.get(collector) or "MISSING").upper()
        if state != "GREEN":
            bad[collector] = state
    return {"ok": not bad, "bad": bad, "reason": None if not bad else "CRITICAL_COLLECTOR_NOT_GREEN"}


def verifier_budget_ressources(usage: Mapping[str, float], limits: Mapping[str, float]) -> dict[str, Any]:
    exceeded: dict[str, dict[str, float]] = {}
    for key, limit in limits.items():
        lim = _positive_number(limit, name=f"limit_{key}")
        val = _positive_number(usage.get(key, 0.0), name=f"usage_{key}", allow_zero=True)
        if val > lim:
            exceeded[key] = {"usage": val, "limit": lim}
    return {"ok": not exceeded, "exceeded": exceeded, "reason": None if not exceeded else "COLLECTOR_RESOURCE_BUDGET_EXCEEDED"}


def verifier_backpressure(*, queue_depth: int, queue_capacity: int, dropped_events: int) -> dict[str, Any]:
    capacity = int(queue_capacity)
    depth = int(queue_depth)
    dropped = int(dropped_events)
    if capacity <= 0 or depth < 0 or dropped < 0:
        raise PreRunInvariantError("BACKPRESSURE_METRIC_INVALID")
    ratio = depth / capacity
    ok = depth <= capacity and dropped == 0
    return {"ok": ok, "fill_ratio": ratio, "dropped_events": dropped, "reason": None if ok else "BACKPRESSURE_DEGRADED"}


# AUD-292..298 ----------------------------------------------------------------
def valider_checkpoint(checkpoint: Mapping[str, Any], *, active_families: Sequence[str]) -> dict[str, Any]:
    missing = sorted(field for field in CHECKPOINT_REQUIRED if checkpoint.get(field) in (None, ""))
    family_state = checkpoint.get("family_state")
    missing_families: list[str] = []
    if isinstance(family_state, Mapping):
        missing_families = sorted(f for f in active_families if f not in family_state)
    else:
        missing_families = sorted(active_families)
    ok = not missing and not missing_families
    return {
        "ok": ok,
        "missing": missing,
        "missing_families": missing_families,
        "reason": None if ok else "CHECKPOINT_INCOMPLETE",
    }


def valider_reprise_checkpoint(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    same_run = before.get("run_id") == after.get("run_id") and bool(before.get("run_id"))
    same_fp = before.get("data_fingerprint") == after.get("data_fingerprint") and bool(before.get("data_fingerprint"))
    counters_ok = all(int(after.get("counters", {}).get(k, 0)) >= int(v) for k, v in dict(before.get("counters", {})).items())
    ok = same_run and same_fp and counters_ok
    return {"ok": ok, "same_run": same_run, "same_fingerprint": same_fp, "counters_monotonic": counters_ok, "reason": None if ok else "CHECKPOINT_RESUME_MISMATCH"}


def construire_autopsie_incident(*, run_id: str, process: str, exception_type: str, last_checkpoint: str | None, last_event_id: str | None) -> dict[str, Any]:
    if not run_id or not process or not exception_type:
        raise PreRunInvariantError("INCIDENT_AUTOPSY_INCOMPLETE")
    return {
        "run_id": run_id,
        "process": process,
        "exception_type": exception_type,
        "last_checkpoint": last_checkpoint,
        "last_event_id": last_event_id,
        "incident_id": stable_fingerprint([run_id, process, exception_type, last_checkpoint, last_event_id])[:24],
    }


def verifier_reprise_windows(*, pre_boot_checkpoint: Mapping[str, Any], post_boot_checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    result = valider_reprise_checkpoint(pre_boot_checkpoint, post_boot_checkpoint)
    result["reboot_proof"] = bool(post_boot_checkpoint.get("boot_id")) and post_boot_checkpoint.get("boot_id") != pre_boot_checkpoint.get("boot_id")
    result["ok"] = bool(result["ok"] and result["reboot_proof"])
    if not result["ok"]:
        result["reason"] = "WINDOWS_REBOOT_RESUME_UNPROVEN"
    return result


def detecter_discontinuite_alimentation(*, previous_monotonic_ns: int, current_monotonic_ns: int, previous_wall_ms: int, current_wall_ms: int, tolerance_ms: int) -> dict[str, Any]:
    mono_ms = (int(current_monotonic_ns) - int(previous_monotonic_ns)) / 1_000_000
    wall_ms = int(current_wall_ms) - int(previous_wall_ms)
    gap_ms = abs(wall_ms - mono_ms)
    discontinuity = mono_ms < 0 or wall_ms < 0 or gap_ms > int(tolerance_ms)
    return {"ok": not discontinuity, "gap_ms": gap_ms, "reason": None if not discontinuity else "SUSPEND_RESUME_DISCONTINUITY"}


def verifier_drift_horloge_locale(*, reference_ms: int, local_ms: int, max_abs_drift_ms: int) -> dict[str, Any]:
    drift = int(local_ms) - int(reference_ms)
    ok = abs(drift) <= int(max_abs_drift_ms)
    return {"ok": ok, "drift_ms": drift, "reason": None if ok else "LOCAL_CLOCK_DRIFT"}


# AUD-299/300 -----------------------------------------------------------------
def atomic_write_text(path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8") -> None:
    """Write+fsync+atomic replace.  The directory is fsynced where supported."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        try:
            dir_fd = os.open(target.parent, os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


__all__ = [
    "PreRunInvariantError", "stable_fingerprint", "construire_catalogue_signaux", "verifier_signaux_utilises",
    "construire_lineage_ledger", "verifier_provenance_forte", "construire_symbol_master", "calculer_notional_quote",
    "valider_fee_schedule", "cout_cross_venue_bps", "canonicaliser_timestamp_ms", "verifier_drift_lead_lag",
    "normaliser_evenement_marche", "comparer_staleness_intervenue", "lire_prix_semantique", "construire_evidence_bundle",
    "shadow_record_brut", "replay_deterministe", "valider_data_contract", "valider_book_granularity", "cle_dedup_coinbase",
    "avancer_cursor_idempotent", "configurer_sqlite_strict", "transaction_sqlite_atomique", "valider_schema_version",
    "valider_retention_reproductible", "valider_archive_auditable", "nouveau_run_context", "verifier_run_id_commun",
    "correlation_id", "log_structure", "agreger_sante_collecteurs", "verifier_budget_ressources", "verifier_backpressure",
    "valider_checkpoint", "valider_reprise_checkpoint", "construire_autopsie_incident", "verifier_reprise_windows",
    "detecter_discontinuite_alimentation", "verifier_drift_horloge_locale", "atomic_write_text",
]

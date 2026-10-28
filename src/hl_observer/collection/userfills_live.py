"""FLUX userFills LIVE → snapshots frais (rectif Flo 23/07). Cœur PUR, testable sans réseau.

Au lieu d'attendre un snapshot toutes les 300 s, on met à jour la position d'un vault DÈS chaque fill
WS `userFills` : on SEED depuis le dernier snapshot connu (positions par coin), puis on applique chaque
fill (szi += signe×sz). On émet alors un snapshot FRAIS que la détection existante (signaux_vaults)
consomme immédiatement — l'ouverture devient event-driven, et plusieurs petits OPEN/ADD s'AGRÈGENT
naturellement dans la position. Le collecteur réseau (`tools/collecter_userfills_vaults.py`) n'est que
la boucle WS autour de ces fonctions. Lecture seule. 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.realtime.event_identity import canonicalize_frame

_EPS = 1e-12
_AUDIT_FILL_FIELDS = (
    "time", "coin", "px", "sz", "side", "dir", "startPosition", "tid", "oid", "hash",
)


def _audit_value(value: Any, *, depth: int = 0) -> Any:
    """Bound and JSON-sanitize an untrusted fill value for rejection diagnostics."""
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value if value.bit_length() <= 256 else {"type": "int", "repr": str(value)[:128]}
    if type(value) is float:
        return value if math.isfinite(value) else {"type": "float", "repr": repr(value)}
    if isinstance(value, str):
        return value if len(value) <= 256 else {"type": "str", "prefix": value[:256], "truncated": True}
    if depth >= 3:
        return {"type": type(value).__name__, "truncated": True}
    if isinstance(value, Mapping):
        result = {
            str(key)[:80]: _audit_value(item, depth=depth + 1)
            for key, item in list(value.items())[:32]
        }
        if len(value) > 32:
            result["_truncated_fields"] = len(value) - 32
        return result
    if isinstance(value, (list, tuple)):
        result = [_audit_value(item, depth=depth + 1) for item in value[:32]]
        if len(value) > 32:
            result.append({"_truncated_items": len(value) - 32})
        return result
    return {"type": type(value).__name__, "repr": repr(value)[:256]}


def _audit_raw_fill(fill: Any) -> Any:
    if not isinstance(fill, Mapping):
        return _audit_value(fill)
    return {
        key: _audit_value(fill[key])
        for key in _AUDIT_FILL_FIELDS
        if key in fill
    }


def userfill_required_fields_reason(
    fill: object,
    *,
    received_at_ms: object = None,
    require_receive: bool = False,
) -> str | None:
    """Explain why a native userFills row cannot identify a causal trade."""
    if not isinstance(fill, Mapping):
        return "FILL_ROW_NOT_OBJECT"
    if not preserve_native_instrument_symbol(fill.get("coin")):
        return "FILL_NATIVE_INSTRUMENT_MISSING"
    timestamp = fill.get("time")
    if type(timestamp) is not int or timestamp <= 0:
        return "FILL_CAUSAL_TIMESTAMP_INVALID"
    if require_receive and (type(received_at_ms) is not int or received_at_ms <= 0):
        return "FILL_RECEIVE_TIMESTAMP_INVALID"
    if received_at_ms is not None and (
        type(received_at_ms) is not int
        or received_at_ms <= 0
        or timestamp > received_at_ms
    ):
        return "FILL_CAUSAL_TIMESTAMP_INVALID"
    if isinstance(fill.get("px"), bool) or isinstance(fill.get("sz"), bool):
        return "FILL_EXECUTION_VALUE_INVALID"
    try:
        price = float(fill.get("px"))
        size = float(fill.get("sz"))
    except (TypeError, ValueError, OverflowError):
        return "FILL_EXECUTION_VALUE_INVALID"
    if not math.isfinite(price) or price <= 0 or not math.isfinite(size) or size <= 0:
        return "FILL_EXECUTION_VALUE_INVALID"
    if "startPosition" in fill:
        raw_start = fill.get("startPosition")
        if raw_start is None or isinstance(raw_start, bool):
            return "FILL_START_POSITION_INVALID"
        try:
            start_position = float(raw_start)
        except (TypeError, ValueError, OverflowError):
            return "FILL_START_POSITION_INVALID"
        if not math.isfinite(start_position):
            return "FILL_START_POSITION_INVALID"
    if str(fill.get("side") or "").upper() not in {"A", "B"}:
        return "FILL_SIDE_INVALID"
    native_hash = fill.get("hash")
    has_hash = isinstance(native_hash, str) and bool(native_hash.strip())
    tid = fill.get("tid")
    has_tid = (type(tid) is int and tid >= 0) or (
        isinstance(tid, str) and tid.strip().isdecimal()
    )
    if not has_hash and not has_tid:
        return "FILL_NATIVE_ID_MISSING"
    return None


def positions_depuis_snapshot(snap: dict) -> dict[str, dict]:
    """{coin: {szi, entryPx}} depuis un snapshot vault (seed de l'état live)."""
    out: dict[str, dict] = {}
    for p in (snap.get("positions") or []):
        c = preserve_native_instrument_symbol(p.get("coin"))
        if c:
            out[c] = {"szi": float(p.get("szi") or 0.0), "entryPx": float(p.get("entryPx") or 0.0)}
    return out


def appliquer_fill(positions: dict[str, dict], fill: dict) -> dict[str, dict]:
    """Applique UN fill à l'état des positions, avec prix d'entrée économiquement exact.

    - OPEN : prix du fill ;
    - ADD même sens : moyenne pondérée par les tailles ;
    - REDUCE/CLOSE : prix d'entrée historique inchangé ;
    - FLIP en un fill : l'ancienne position est fermée puis le reliquat opposé est ouvert au prix du fill.

    Le calcul reste en place et n'invente aucun prix intermédiaire.
    """
    c = preserve_native_instrument_symbol(fill.get("coin"))
    if not c:
        return positions
    raw_sign = fill.get("signe")
    if isinstance(raw_sign, bool):
        return positions
    try:
        sz = float(fill.get("sz"))
        signe = int(raw_sign)
        px = float(fill.get("px"))
    except (TypeError, ValueError, OverflowError):
        return positions
    if (
        not math.isfinite(sz) or sz <= _EPS
        or not math.isfinite(px) or px <= 0.0
        or signe not in (-1, 1)
    ):
        return positions

    cur = positions.setdefault(c, {"szi": 0.0, "entryPx": px})
    avant = float(cur.get("szi") or 0.0)
    entry_avant = float(cur.get("entryPx") or 0.0)
    delta = signe * sz
    apres = round(avant + delta, 10)

    if abs(avant) <= _EPS:
        # Nouvelle position depuis zéro.
        entry_apres = px
    elif (avant > 0) == (delta > 0):
        # Renforcement dans le même sens : coût moyen pondéré, pas « dernier fill ».
        ancien_notional_prix = abs(avant) * (entry_avant if entry_avant > 0 else px)
        entry_apres = (ancien_notional_prix + sz * px) / (abs(avant) + sz)
    elif abs(apres) <= _EPS:
        # CLOSE : le prix d'entrée n'a plus d'impact tant que la position reste nulle.
        entry_apres = entry_avant
    elif (avant > 0) == (apres > 0):
        # REDUCE sans traverser zéro : coût de base historique inchangé.
        entry_apres = entry_avant
    else:
        # FLIP : le reliquat opposé est une nouvelle position exécutée à CE prix.
        entry_apres = px

    cur["szi"] = 0.0 if abs(apres) <= _EPS else apres
    cur["entryPx"] = float(entry_apres)
    return positions


def snapshot_depuis_positions(vault: str, positions: dict[str, dict], *, nav_usd: float, ts_ms: int) -> dict:
    """Reconstruit un snapshot vault FRAIS (même format que collecter_vaults) depuis l'état live. On garde
    le NAV du dernier snapshot connu (le NAV bouge lentement ; l'important ici c'est le szi live)."""
    pos = [{"coin": c, "szi": round(v["szi"], 8), "entryPx": v["entryPx"]}
           for c, v in positions.items() if abs(v["szi"]) > _EPS]
    return {"vault": vault, "ts_ms": int(ts_ms), "nav_usd": float(nav_usd), "positions": pos,
            "n_positions": len(pos), "source": "userfills_live", "read_only": True, "real_execution": False}


def parser_message_userfills(
    msg: Any,
    *,
    vault: str = "",
    received_at_ms: int | None = None,
    receive_mono_ns: int | None = None,
    connection_id: str | None = None,
    audit: dict[str, Any] | None = None,
) -> list[dict]:
    """Normalise un message WS userFills en conservant DEUX horloges distinctes.

    ``ts_ms`` vient de l'exchange (fill ``time``). ``received_at_ms`` est l'heure murale locale de
    réception du frame WS, injectée par le collecteur au plus près de ``ws.recv``. Si elle manque ou est
    invalide, elle reste ``None`` : ni l'heure courante ni le timestamp exchange ne la remplacent.
    Cela évite de fabriquer une latence ou une preuve causale.

    `isSnapshot` est propagé (le snapshot initial rejoue l'historique : à IGNORER pour trader). Tolérant.
    Le champ `liquidation` de WsFill est préservé lorsqu'il existe.
    """
    data = msg.get("data") if isinstance(msg, dict) else None
    fills = (data or {}).get("fills") if isinstance(data, dict) else None
    snapshot_value = data.get("isSnapshot") if isinstance(data, dict) else None
    # Missing or malformed isSnapshot is unknown, never an implicit live event.
    est_snapshot = snapshot_value if type(snapshot_value) is bool else None
    sequence_raw = msg.get("sequence", msg.get("seq")) if isinstance(msg, dict) else None
    if sequence_raw is None and isinstance(data, dict):
        sequence_raw = data.get("sequence", data.get("seq"))
    try:
        frame_sequence = int(sequence_raw) if sequence_raw is not None else None
    except (TypeError, ValueError, OverflowError):
        frame_sequence = None
    frame_received_at_ms: int | None = None
    if isinstance(received_at_ms, int) and not isinstance(received_at_ms, bool):
        frame_received_at_ms = received_at_ms if received_at_ms > 0 else None
    elif isinstance(received_at_ms, str) and received_at_ms.strip().isdecimal():
        try:
            parsed_received_at_ms = int(received_at_ms.strip())
        except (ValueError, OverflowError):
            parsed_received_at_ms = 0
        frame_received_at_ms = parsed_received_at_ms if parsed_received_at_ms > 0 else None

    rejected_by_reason: dict[str, int] = {}
    rejected_samples: list[dict[str, Any]] = []

    def reject(index: int | None, reason: str, raw_fill: Any) -> None:
        rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
        if len(rejected_samples) < 20:
            rejected_samples.append({
                "index": index,
                "reason_code": reason,
                "source": "LIVE_WS",
                "received_at_ms": frame_received_at_ms,
                "connection_id": connection_id,
                "frame_sequence": frame_sequence,
                "raw_payload": _audit_raw_fill(raw_fill),
            })

    raw_fill_count: int | None = len(fills) if isinstance(fills, list) else None
    raw_fills: list[Mapping[str, Any]] = []
    source_indexes: list[int] = []
    if not isinstance(fills, list):
        reject(None, "USERFILLS_LIST_INVALID", fills)
    else:
        for index, item in enumerate(fills):
            if not isinstance(item, Mapping):
                reject(index, "FILL_ROW_NOT_OBJECT", item)
                continue
            reason = userfill_required_fields_reason(
                item, received_at_ms=frame_received_at_ms,
            )
            if reason is not None:
                reject(index, reason, item)
                continue
            raw_fills.append(item)
            source_indexes.append(index)
    frame_events = canonicalize_frame(
        raw_fills,
        source="LIVE_WS",
        channel="userFills",
        received_at_ms=frame_received_at_ms,
        frame_sequence=frame_sequence,
    )
    out: list[dict] = []
    for frame_event in frame_events:
        f = frame_event.payload
        reason = userfill_required_fields_reason(
            f,
            received_at_ms=frame_event.received_at_ms,
        )
        original_index = source_indexes[frame_event.event_index_in_frame]
        if reason is not None:
            reject(original_index, reason, f)
            continue
        try:
            coin = preserve_native_instrument_symbol(f["coin"])
            px = float(f["px"])
            sz = float(f["sz"])
            ts = f["time"]
        except (KeyError, TypeError, ValueError):
            continue
        side = str(f.get("side") or "").upper()
        try:
            start_pos = float(f.get("startPosition"))
        except (TypeError, ValueError, OverflowError):
            start_pos = None
        entry = {"vault": vault, "coin": coin, "px": px, "sz": sz,
                 "signe": 1 if side == "B" else (-1 if side == "A" else 0),
                 "ts_ms": ts, "received_at_ms": frame_event.received_at_ms,
                 "dir": str(f.get("dir") or ""), "hash": f.get("hash"),
                 "tid": f.get("tid"), "oid": f.get("oid"),
                 "start_position": start_pos, "isSnapshot": est_snapshot,
                 "source": "LIVE_WS",
                 "recv_mono_ns": (
                     receive_mono_ns
                     if type(receive_mono_ns) is int and receive_mono_ns > 0
                     else None
                 ),
                 "connection_id": str(connection_id) if connection_id else None,
                 "frame_sequence": frame_event.frame_sequence,
                 "event_index_in_frame": frame_event.event_index_in_frame,
                 "stable_event_id": frame_event.stable_event_id}
        liq = f.get("liquidation")
        if liq:
            entry["liquidation"] = liq
        out.append(entry)
    if audit is not None:
        audit.clear()
        audit.update({
            "input_count": raw_fill_count,
            "accepted_count": len(out),
            "rejected_count": sum(rejected_by_reason.values()),
            "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
            "rejected_samples": rejected_samples,
            "frame_sequence": frame_sequence,
            "received_at_ms": frame_received_at_ms,
            "connection_id": connection_id,
        })
    return out


def liquidations_confirmees(fills: list[dict]) -> list[dict]:
    """Fills normalisés PORTANT un `liquidation` non-null → records aplatis de liquidations CONFIRMÉES.
    Provenance = REAL_LIQUIDATION (fill.liquidation), JAMAIS un proxy mark/oracle. Prêt pour le journal
    `liquidations_confirmees.jsonl` et la jointure BBO/L2 synchronisée. 0 réseau, pur, testable."""
    out: list[dict] = []
    for f in (fills or []):
        liq = f.get("liquidation")
        if not liq:
            continue
        out.append({"vault": f.get("vault"), "coin": f.get("coin"), "px": f.get("px"), "sz": f.get("sz"),
                    "signe": f.get("signe"), "ts_ms": f.get("ts_ms"), "dir": f.get("dir"), "hash": f.get("hash"),
                    "tid": f.get("tid"), "oid": f.get("oid"),
                    "is_snapshot": f.get("isSnapshot"),
                    "frame_sequence": f.get("frame_sequence"),
                    "event_index_in_frame": f.get("event_index_in_frame"),
                    "stable_event_id": f.get("stable_event_id"),
                    "liquidatedUser": liq.get("liquidatedUser"), "markPx": liq.get("markPx"),
                    "method": liq.get("method"), "provenance": "REAL_LIQUIDATION",
                    "source": "userFills.liquidation"})
    return out


__all__ = ["positions_depuis_snapshot", "appliquer_fill", "snapshot_depuis_positions",
           "parser_message_userfills", "liquidations_confirmees"]

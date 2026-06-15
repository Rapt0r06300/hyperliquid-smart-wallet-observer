from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LOGS_TO_SEND_DIRNAME = "logs \u00e0 envoyer"
DECISION_LOG_FILES = (
    "simulation_decisions_latest.jsonl",
    "cli_simulation_decisions_latest.jsonl",
    "simulation_decisions_append_only.jsonl",
)
STRUCTURED_DECISION_LOG = ("structured", "decisions.jsonl")
SUMMARY_CACHE_FILE = "simulation_log_summary_cache.json"
SUMMARY_CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    timestamp_ms: int | None
    wallet_address: str | None
    coin: str | None
    leader_action: str | None
    leader_side: str | None
    bot_decision: str
    status: str
    reason: str
    plain_english: str
    edge_remaining_bps: float | None
    copy_degradation_bps: float | None
    signal_age_ms: int | None
    consensus_wallets: int | None
    copied_notional_usdt: float | None
    estimated_net_pnl_usdc: float | None
    gross_pnl_usdc: float | None
    fee_cost_usdc: float | None
    execution: str
    research_only: bool


@dataclass(frozen=True, slots=True)
class ReplayAnalysis:
    source_dir: Path
    events: tuple[DecisionEvent, ...]
    event_count: int
    accepted_count: int
    refused_count: int
    positive_count: int
    negative_count: int
    total_estimated_pnl_usdc: float
    total_fees_usdc: float
    top_refusal_reasons: tuple[tuple[str, int], ...]
    pnl_by_coin: dict[str, float] = field(default_factory=dict)
    pnl_by_wallet: dict[str, float] = field(default_factory=dict)
    action_counts: dict[str, int] = field(default_factory=dict)


def default_logs_to_send_dir(root: Path = Path(".")) -> Path:
    return root / "logs" / LOGS_TO_SEND_DIRNAME


def load_decision_events(log_dir: Path) -> tuple[DecisionEvent, ...]:
    for path in _decision_file_candidates(log_dir):
        if path.exists() and path.stat().st_size > 0:
            return tuple(_row_to_event(row) for row in _read_jsonl(path))
    return ()


def load_recent_decision_events(log_dir: Path, *, limit: int = 100) -> tuple[DecisionEvent, ...]:
    """Load recent events without decoding a very large append-only log.

    The dashboard and realtime replay only need the tail of the stream. Loading
    the whole 1GB+ append-only JSONL made the UI look frozen and could make the
    realtime freshness gate expire while the gate itself was running.
    """

    path = _primary_decision_file(log_dir)
    if path is None or limit <= 0:
        return ()
    rows = _read_recent_jsonl(path, limit=limit)
    return tuple(_row_to_event(row) for row in rows)


def analyze_decision_logs(log_dir: Path) -> ReplayAnalysis:
    events = load_decision_events(log_dir)
    return _analysis_from_events(log_dir, events)


def analyze_decision_logs_summary(log_dir: Path) -> ReplayAnalysis:
    """Return aggregate log metrics with a source-validated runtime cache.

    This keeps quality gates fast while preserving honesty: the cache is reused
    only when the source JSONL path, size and mtime match exactly. If the log
    changes, the summary is recomputed from the real rows.
    """

    path = _primary_decision_file(log_dir)
    if path is None:
        return _analysis_from_events(log_dir, ())
    signature = _file_signature(path)
    cached = _read_summary_cache(log_dir, signature)
    if cached is not None:
        return cached
    analysis = _stream_summary_from_file(log_dir, path)
    _write_summary_cache(log_dir, path, signature, analysis)
    return analysis


def count_decision_events_fast(log_dir: Path) -> int:
    path = _primary_decision_file(log_dir)
    if path is None:
        return 0
    cached = _read_summary_cache(log_dir, _file_signature(path))
    if cached is not None:
        return cached.event_count
    return _count_nonempty_lines(path)


def _analysis_from_events(log_dir: Path, events: tuple[DecisionEvent, ...]) -> ReplayAnalysis:
    reasons: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    pnl_by_coin: defaultdict[str, float] = defaultdict(float)
    pnl_by_wallet: defaultdict[str, float] = defaultdict(float)
    total_pnl = 0.0
    total_fees = 0.0
    accepted = refused = positive = negative = 0
    for event in events:
        actions[event.bot_decision] += 1
        if event.status.upper() == "REFUSED":
            refused += 1
            if event.reason:
                reasons[event.reason] += 1
        else:
            accepted += 1
        pnl = event.estimated_net_pnl_usdc or 0.0
        fee = event.fee_cost_usdc or 0.0
        total_pnl += pnl
        total_fees += fee
        if pnl > 0:
            positive += 1
        if pnl < 0:
            negative += 1
        if event.coin:
            pnl_by_coin[event.coin] += pnl
        if event.wallet_address:
            pnl_by_wallet[event.wallet_address] += pnl
    return ReplayAnalysis(
        source_dir=log_dir,
        events=events,
        event_count=len(events),
        accepted_count=accepted,
        refused_count=refused,
        positive_count=positive,
        negative_count=negative,
        total_estimated_pnl_usdc=round(total_pnl, 8),
        total_fees_usdc=round(total_fees, 8),
        top_refusal_reasons=tuple(reasons.most_common(20)),
        pnl_by_coin={key: round(value, 8) for key, value in sorted(pnl_by_coin.items())},
        pnl_by_wallet={key: round(value, 8) for key, value in sorted(pnl_by_wallet.items())},
        action_counts=dict(actions),
    )


def _stream_summary_from_file(log_dir: Path, path: Path) -> ReplayAnalysis:
    reasons: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    pnl_by_coin: defaultdict[str, float] = defaultdict(float)
    pnl_by_wallet: defaultdict[str, float] = defaultdict(float)
    total_pnl = 0.0
    total_fees = 0.0
    accepted = refused = positive = negative = event_count = 0
    for raw in _iter_jsonl_rows(path):
        event = _row_to_event(raw)
        event_count += 1
        actions[event.bot_decision] += 1
        if event.status.upper() == "REFUSED":
            refused += 1
            if event.reason:
                reasons[event.reason] += 1
        else:
            accepted += 1
        pnl = event.estimated_net_pnl_usdc or 0.0
        fee = event.fee_cost_usdc or 0.0
        total_pnl += pnl
        total_fees += fee
        if pnl > 0:
            positive += 1
        if pnl < 0:
            negative += 1
        if event.coin:
            pnl_by_coin[event.coin] += pnl
        if event.wallet_address:
            pnl_by_wallet[event.wallet_address] += pnl
    return ReplayAnalysis(
        source_dir=log_dir,
        events=(),
        event_count=event_count,
        accepted_count=accepted,
        refused_count=refused,
        positive_count=positive,
        negative_count=negative,
        total_estimated_pnl_usdc=round(total_pnl, 8),
        total_fees_usdc=round(total_fees, 8),
        top_refusal_reasons=tuple(reasons.most_common(20)),
        pnl_by_coin={key: round(value, 8) for key, value in sorted(pnl_by_coin.items())},
        pnl_by_wallet={key: round(value, 8) for key, value in sorted(pnl_by_wallet.items())},
        action_counts=dict(actions),
    )


def format_replay_analysis(analysis: ReplayAnalysis) -> str:
    lines = [
        "simulation_log_analysis=local_read_only",
        f"source_dir={analysis.source_dir}",
        f"events={analysis.event_count}",
        f"accepted={analysis.accepted_count}",
        f"refused={analysis.refused_count}",
        f"positive_events={analysis.positive_count}",
        f"negative_events={analysis.negative_count}",
        f"estimated_net_pnl_usdc={analysis.total_estimated_pnl_usdc:.6f}",
        f"fees_usdc={analysis.total_fees_usdc:.6f}",
    ]
    if analysis.top_refusal_reasons:
        lines.append("top_refusal_reasons:")
        lines.extend(f"- {reason}: {count}" for reason, count in analysis.top_refusal_reasons)
    if analysis.action_counts:
        lines.append("action_counts:")
        lines.extend(f"- {action}: {count}" for action, count in sorted(analysis.action_counts.items()))
    return "\n".join(lines)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _iter_jsonl_rows(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def _read_recent_jsonl(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    chunk_size = 64 * 1024
    chunks: list[bytes] = []
    lines_seen = 0
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        while position > 0 and lines_seen <= limit:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            lines_seen += chunk.count(b"\n")
    raw = b"".join(reversed(chunks)).decode("utf-8-sig", errors="replace")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _count_nonempty_lines(path: Path) -> int:
    count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            count += chunk.count(b"\n")
    return count


def _primary_decision_file(log_dir: Path) -> Path | None:
    for path in _decision_file_candidates(log_dir):
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def _decision_file_candidates(log_dir: Path) -> tuple[Path, ...]:
    """Return decision logs in UI-friendly priority order.

    The old HyperSmart exporter writes under ``logs/logs à envoyer`` while the
    dYdX simulation engine writes append-only structured decisions under
    ``logs/structured/decisions.jsonl``. Prefer the small/latest files first,
    then the dYdX structured log, and keep the huge append-only export last so a
    dashboard refresh cannot freeze on a multi-GB historical file.
    """

    structured = log_dir.parent.joinpath(*STRUCTURED_DECISION_LOG)
    return (
        log_dir / "simulation_decisions_latest.jsonl",
        structured,
        log_dir / "cli_simulation_decisions_latest.jsonl",
        log_dir / "simulation_decisions_append_only.jsonl",
    )


def _file_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "source_path": str(path.resolve()),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
    }


def _read_summary_cache(log_dir: Path, signature: dict[str, Any]) -> ReplayAnalysis | None:
    cache_path = log_dir / SUMMARY_CACHE_FILE
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("version") != SUMMARY_CACHE_VERSION:
        return None
    if payload.get("signature") != signature:
        return None
    return ReplayAnalysis(
        source_dir=log_dir,
        events=(),
        event_count=int(payload.get("event_count") or 0),
        accepted_count=int(payload.get("accepted_count") or 0),
        refused_count=int(payload.get("refused_count") or 0),
        positive_count=int(payload.get("positive_count") or 0),
        negative_count=int(payload.get("negative_count") or 0),
        total_estimated_pnl_usdc=float(payload.get("total_estimated_pnl_usdc") or 0.0),
        total_fees_usdc=float(payload.get("total_fees_usdc") or 0.0),
        top_refusal_reasons=tuple((str(reason), int(count)) for reason, count in payload.get("top_refusal_reasons", [])),
        pnl_by_coin={str(k): float(v) for k, v in dict(payload.get("pnl_by_coin") or {}).items()},
        pnl_by_wallet={str(k): float(v) for k, v in dict(payload.get("pnl_by_wallet") or {}).items()},
        action_counts={str(k): int(v) for k, v in dict(payload.get("action_counts") or {}).items()},
    )


def _write_summary_cache(log_dir: Path, path: Path, signature: dict[str, Any], analysis: ReplayAnalysis) -> None:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / SUMMARY_CACHE_FILE).write_text(
            json.dumps(
                {
                    "version": SUMMARY_CACHE_VERSION,
                    "signature": signature,
                    "source_file": str(path),
                    "event_count": analysis.event_count,
                    "accepted_count": analysis.accepted_count,
                    "refused_count": analysis.refused_count,
                    "positive_count": analysis.positive_count,
                    "negative_count": analysis.negative_count,
                    "total_estimated_pnl_usdc": analysis.total_estimated_pnl_usdc,
                    "total_fees_usdc": analysis.total_fees_usdc,
                    "top_refusal_reasons": list(analysis.top_refusal_reasons),
                    "pnl_by_coin": analysis.pnl_by_coin,
                    "pnl_by_wallet": analysis.pnl_by_wallet,
                    "action_counts": analysis.action_counts,
                    "read_only": True,
                    "execution": "forbidden",
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def _row_to_event(row: dict[str, Any]) -> DecisionEvent:
    event_type = _to_str(row.get("event_type"))
    return DecisionEvent(
        timestamp_ms=_to_int(row.get("timestamp_ms") or row.get("recorded_at_ms") or row.get("closed_at_ms")),
        wallet_address=_to_str(row.get("wallet_address") or row.get("leader_wallet")),
        coin=_to_str(row.get("coin") or row.get("market_id")),
        leader_action=_to_str(row.get("leader_action") or row.get("action") or event_type),
        leader_side=_to_str(row.get("leader_side") or row.get("side")),
        bot_decision=_to_str(row.get("bot_decision") or row.get("action") or event_type or "UNKNOWN") or "UNKNOWN",
        status=_event_status(row),
        reason=_to_str(row.get("reason") or "") or "",
        plain_english=_to_str(row.get("plain_english") or row.get("detail") or "") or "",
        edge_remaining_bps=_to_float(row.get("edge_remaining_bps")),
        copy_degradation_bps=_to_float(row.get("copy_degradation_bps")),
        signal_age_ms=_to_int(row.get("signal_age_ms")),
        consensus_wallets=_to_int(row.get("consensus_wallets") or row.get("wallet_count")),
        copied_notional_usdt=_to_float(row.get("copied_notional_usdt") or row.get("notional") or row.get("size")),
        estimated_net_pnl_usdc=_event_net_pnl(row),
        gross_pnl_usdc=_to_float(row.get("gross_pnl_usdc") or row.get("gross_pnl")),
        fee_cost_usdc=_event_fee(row),
        execution=_to_str(row.get("execution") or "forbidden") or "forbidden",
        research_only=bool(row.get("research_only", True)),
    )


def _event_status(row: dict[str, Any]) -> str:
    status = _to_str(row.get("status"))
    if status:
        return status
    event_type = (_to_str(row.get("event_type")) or "").upper()
    if event_type == "NO_TRADE":
        return "REFUSED"
    if event_type.startswith("PAPER_"):
        return "LOCAL_REPLAY"
    return "LOCAL_REPLAY"


def _event_net_pnl(row: dict[str, Any]) -> float | None:
    """Return event-level PnL, not a cumulative session balance.

    dYdX structured rows carry ``net_pnl_usdc`` as the current cumulative
    session PnL. Summing that field across rows is wrong and explains confusing
    dashboard totals. For structured rows, use per-event fields instead:
    entry fee on open, realized net on close/partial TP, zero on no-trade.
    """

    event_type = (_to_str(row.get("event_type")) or "").upper()
    if event_type == "NO_TRADE":
        return 0.0
    if event_type == "PAPER_OPEN":
        fee = _to_float(row.get("fee_paid") or row.get("fee_cost_usdc") or row.get("fee"))
        return -fee if fee is not None else 0.0
    if event_type in {"PAPER_CLOSE", "PAPER_PARTIAL_TP"}:
        pnl = _to_float(row.get("net_pnl") or row.get("event_net_pnl_usdc"))
        return pnl if pnl is not None else 0.0
    return _to_float(row.get("estimated_net_pnl_usdc") or row.get("realized_pnl"))


def _event_fee(row: dict[str, Any]) -> float | None:
    event_type = (_to_str(row.get("event_type")) or "").upper()
    if event_type == "PAPER_OPEN":
        return _to_float(row.get("fee_paid") or row.get("fee_cost_usdc") or row.get("fee"))
    if event_type in {"PAPER_CLOSE", "PAPER_PARTIAL_TP"}:
        gross = _to_float(row.get("gross_pnl") or row.get("gross_pnl_usdc"))
        net = _to_float(row.get("net_pnl") or row.get("event_net_pnl_usdc"))
        if gross is not None and net is not None:
            return abs(gross - net)
    return _to_float(row.get("fee_cost_usdc") or row.get("fee"))


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

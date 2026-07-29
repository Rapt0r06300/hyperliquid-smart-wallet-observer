"""Build fusion runtime input from local Hyperliquid paper-simulation artifacts.

This is a small bridge between the live scanner and the UI fusion runtime. It
does not fetch the network and does not invent wallets: it only consumes recent
``position_deltas`` and local ``market_snapshots`` written by the read-only
collectors.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from hl_observer.ops.echec_silencieux import noter as _noter_echec
from hl_observer.simulation.accounting_truth import first_not_none
from hl_observer.storage.models import MarketSnapshot, PositionDeltaModel, TopWallet
from hl_observer.utils.time import now_ms

ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE", "ADD_LONG", "ADD_SHORT", "INCREASE_LONG", "INCREASE_SHORT"}
DEFAULT_FRESH_WINDOW_MS = 60_000
DEFAULT_MAX_VOTES = 24


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON without exposing readers to a partially written status file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    last_error: OSError | None = None
    for attempt in range(4):
        try:
            tmp_path.replace(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.035 * (attempt + 1))
    try:
        tmp_path.unlink(missing_ok=True)
    finally:
        if last_error is not None:
            raise last_error


@dataclass(frozen=True, slots=True)
class FusionHeartbeatBuildReport:
    status: str
    message: str
    votes_count: int
    price_events_count: int
    coins: tuple[str, ...]
    reasons: tuple[str, ...]
    fusion_runtime_input: dict[str, Any] | None
    recent_deltas_count: int = 0
    recent_entry_deltas_count: int = 0
    latest_delta_age_ms: int | None = None
    read_only: bool = True
    simulation_only: bool = True
    external_action: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_fusion_runtime_input_from_session(
    session: Session,
    *,
    fresh_window_ms: int = DEFAULT_FRESH_WINDOW_MS,
    max_votes: int = DEFAULT_MAX_VOTES,
    current_ms: int | None = None,
    starting_equity_usdt: float | None = None,
    current_equity_usdt: float | None = None,
    peak_equity_usdt: float | None = None,
    open_exposure_usdt: float | None = None,
) -> FusionHeartbeatBuildReport:
    current_ms = int(current_ms or now_ms())
    cutoff_ms = current_ms - max(1_000, int(fresh_window_ms))
    max_votes = max(1, min(int(max_votes), 100))
    deltas = (
        session.query(PositionDeltaModel)
        .filter(PositionDeltaModel.detected_at_ms.isnot(None))
        .filter(PositionDeltaModel.detected_at_ms >= cutoff_ms)
        .order_by(desc(PositionDeltaModel.detected_at_ms), desc(PositionDeltaModel.id))
        .limit(max_votes * 4)
        .all()
    )
    recent_deltas_count = len(deltas)
    latest_delta_age_ms = _latest_delta_age_ms(session, current_ms=current_ms)
    if not deltas:
        return FusionHeartbeatBuildReport(
            status="NO_FRESH_DELTAS",
            message="Aucun delta recent local; le runtime fusion ne cree pas de signal.",
            votes_count=0,
            price_events_count=0,
            coins=(),
            reasons=("NO_FRESH_DELTAS",),
            fusion_runtime_input=None,
            recent_deltas_count=0,
            recent_entry_deltas_count=0,
            latest_delta_age_ms=latest_delta_age_ms,
        )

    top_scores = _top_wallet_scores(session)
    votes: list[dict[str, Any]] = []
    distilled_signal_candidates: list[dict[str, Any]] = []
    for delta in deltas:
        side = _side_from_delta(delta)
        if side not in {"LONG", "SHORT"}:
            continue
        action = str(delta.action or delta.delta_type or "").upper()
        if not _is_entry_action(action, delta):
            continue
        wallet = str(delta.wallet_address or "")
        coin = str(delta.coin or "").upper()
        if not wallet or not coin:
            continue
        wallet_score = float(top_scores.get(wallet.lower(), 50.0))
        confidence = _safe_float(delta.confidence_score) or 0.0
        notional = abs(_safe_float(delta.delta_notional_usdc) or 0.0)
        vote_score = _vote_score(wallet_score=wallet_score, confidence=confidence, notional=notional)
        votes.append(
            {
                "wallet": wallet,
                "coin": coin,
                "side": side,
                "score": vote_score,
                "observed_at_ms": int(delta.detected_at_ms or delta.exchange_ts or current_ms),
                "source_delta_id": int(delta.id),
                "source": str(delta.source or "position_deltas"),
                "action": action or "UNKNOWN",
                "notional_usdc": round(notional, 6),
                "read_only": True,
            }
        )
        candidate = _distilled_candidate_from_delta(
            delta,
            wallet=wallet,
            coin=coin,
            side=side,
            action=action,
            wallet_score=wallet_score,
            notional=notional,
            current_ms=current_ms,
        )
        if candidate is not None:
            distilled_signal_candidates.append(candidate)
        if len(votes) >= max_votes:
            break

    if not votes:
        return FusionHeartbeatBuildReport(
            status="NO_ENTRY_VOTES",
            message="Deltas recents vus, mais aucun OPEN/ADD/INCREASE directionnel exploitable.",
            votes_count=0,
            price_events_count=0,
            coins=(),
            reasons=("NO_ENTRY_VOTES",),
            fusion_runtime_input=None,
            recent_deltas_count=recent_deltas_count,
            recent_entry_deltas_count=0,
            latest_delta_age_ms=latest_delta_age_ms,
        )

    coins = tuple(sorted({str(vote["coin"]) for vote in votes}))
    mids, mids_ts = _latest_mids(session)
    price_events: list[dict[str, Any]] = []
    missing_prices: list[str] = []
    for coin in coins:
        mid = mids.get(coin)
        if mid is None or mid <= 0:
            missing_prices.append(coin)
            continue
        # allMids is a real Hyperliquid midpoint, not a book. We wrap it in a
        # tiny conservative paper-only synthetic spread so downstream code can
        # consume a bid/ask shape while provenance remains explicit.
        spread = max(mid * 0.0002, 1e-9)
        price_events.append(
            {
                "source": "local_market_snapshot_allMids_derived_bidask",
                "coin": coin,
                "bid": round(mid - spread / 2.0, 10),
                "ask": round(mid + spread / 2.0, 10),
                "event_time_ms": int(mids_ts.get(coin) or current_ms),
                "mid_source": "Hyperliquid allMids local snapshot",
                "derived_bidask": True,
            }
        )

    if not price_events:
        return FusionHeartbeatBuildReport(
            status="NO_REAL_MARKS",
            message="Votes fusion presents, mais aucun mid Hyperliquid local recent pour les prix paper.",
            votes_count=len(votes),
            price_events_count=0,
            coins=coins,
            reasons=tuple(["NO_REAL_MARKS", *[f"MISSING_MARK_{coin}" for coin in missing_prices]]),
            fusion_runtime_input=None,
            recent_deltas_count=recent_deltas_count,
            recent_entry_deltas_count=len(votes),
            latest_delta_age_ms=latest_delta_age_ms,
        )

    usable_coins = {str(event["coin"]) for event in price_events}
    votes = [vote for vote in votes if str(vote["coin"]) in usable_coins]
    distilled_signal_candidates = [
        candidate
        for candidate in distilled_signal_candidates
        if str(candidate.get("coin") or "").upper() in usable_coins
    ]
    if not votes:
        return FusionHeartbeatBuildReport(
            status="NO_VOTES_WITH_MARKS",
            message="Aucun vote ne correspond aux mids Hyperliquid locaux disponibles.",
            votes_count=0,
            price_events_count=len(price_events),
            coins=tuple(sorted(usable_coins)),
            reasons=("NO_VOTES_WITH_MARKS",),
            fusion_runtime_input=None,
            recent_deltas_count=recent_deltas_count,
            recent_entry_deltas_count=0,
            latest_delta_age_ms=latest_delta_age_ms,
        )

    starting_equity = _safe_float(starting_equity_usdt)
    current_equity = _safe_float(current_equity_usdt)
    peak_equity = _safe_float(peak_equity_usdt)
    if starting_equity is None or starting_equity <= 0:
        return FusionHeartbeatBuildReport(
            status="ACCOUNTING_BASELINE_UNAVAILABLE",
            message="Baseline de session absente; aucun input fusion comptable n'est produit.",
            votes_count=len(votes),
            price_events_count=len(price_events),
            coins=tuple(sorted(usable_coins)),
            reasons=("ACCOUNTING_BASELINE_UNAVAILABLE",),
            fusion_runtime_input=None,
            recent_deltas_count=recent_deltas_count,
            recent_entry_deltas_count=len(votes),
            latest_delta_age_ms=latest_delta_age_ms,
        )
    current_equity = float(first_not_none(current_equity, starting_equity))
    peak_equity = float(first_not_none(peak_equity, current_equity))
    payload = {
        "session_id": f"local-fusion-{current_ms}",
        "leader_votes": votes,
        "distilled_signal_candidates": distilled_signal_candidates,
        "price_events": price_events,
        "funding_rows": _build_funding_rows(usable_coins),
        "triangular_edges": [],
        "latencies_ms": [],
        "starting_equity": round(starting_equity, 6),
        "peak_equity": round(peak_equity, 6),
        "current_equity": round(current_equity, 6),
        "open_exposure_usdt": round(
            float(first_not_none(_safe_float(open_exposure_usdt), 0.0)),
            6,
        ),
        "copy_ratio": 0.05,
        "input_source": "local_db_position_deltas_and_market_snapshots",
        "created_at_ms": current_ms,
        "read_only": True,
        "simulation_only": True,
        "external_action": False,
    }
    return FusionHeartbeatBuildReport(
        status="READY",
        message="Input fusion construit depuis deltas locaux recents et mids Hyperliquid locaux.",
        votes_count=len(votes),
        price_events_count=len(price_events),
        coins=tuple(sorted(usable_coins)),
        reasons=(),
        fusion_runtime_input=payload,
        recent_deltas_count=recent_deltas_count,
        recent_entry_deltas_count=len(votes),
        latest_delta_age_ms=latest_delta_age_ms,
    )


def write_fusion_runtime_input_to_engine_status(
    *,
    session: Session,
    engine_status_path: Path,
    fresh_window_ms: int = DEFAULT_FRESH_WINDOW_MS,
    max_votes: int = DEFAULT_MAX_VOTES,
    current_ms: int | None = None,
) -> FusionHeartbeatBuildReport:
    state_summary = _read_ui_state_summary(engine_status_path.with_name("ui_simulation_state.json"))
    report = build_fusion_runtime_input_from_session(
        session,
        fresh_window_ms=fresh_window_ms,
        max_votes=max_votes,
        current_ms=current_ms,
        starting_equity_usdt=state_summary["starting_equity_usdt"],
        current_equity_usdt=state_summary["current_equity_usdt"],
        peak_equity_usdt=state_summary["peak_equity_usdt"],
        open_exposure_usdt=state_summary["open_exposure_usdt"],
    )
    payload = _read_json_object(engine_status_path)
    status_updated_at_ms = int(current_ms or now_ms())
    payload["updated_at_ms"] = status_updated_at_ms
    payload.setdefault("phase", "fusion_runtime_input")
    payload.setdefault("message", report.message)
    payload.setdefault("read_only", True)
    payload.setdefault("simulation_only", True)
    payload["external_action"] = False
    payload["fusion_runtime_input_status"] = report.status
    payload["fusion_runtime_input_message"] = report.message
    if report.fusion_runtime_input is not None:
        payload["fusion_runtime_input"] = report.fusion_runtime_input
    else:
        payload.pop("fusion_runtime_input", None)
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    metrics.update(
        {
            "fusion_runtime_input_status": report.status,
            "fusion_runtime_votes": str(report.votes_count),
            "fusion_runtime_distilled_candidates": str(
                len(report.fusion_runtime_input.get("distilled_signal_candidates", []))
                if isinstance(report.fusion_runtime_input, dict)
                else 0
            ),
            "fusion_runtime_price_events": str(report.price_events_count),
            "fusion_runtime_coins": ",".join(report.coins),
            "fusion_runtime_reasons": ",".join(report.reasons),
            "fusion_runtime_recent_deltas": str(report.recent_deltas_count),
            "fusion_runtime_recent_entry_deltas": str(report.recent_entry_deltas_count),
            "fusion_runtime_latest_delta_age_ms": str(report.latest_delta_age_ms if report.latest_delta_age_ms is not None else ""),
            "fusion_runtime_state_source": state_summary["source"],
            "fusion_runtime_starting_equity_usdt": str(
                state_summary["starting_equity_usdt"]
                if state_summary["starting_equity_usdt"] is not None
                else ""
            ),
            "fusion_runtime_current_equity_usdt": str(
                state_summary["current_equity_usdt"]
                if state_summary["current_equity_usdt"] is not None
                else ""
            ),
            "fusion_runtime_peak_equity_usdt": str(
                state_summary["peak_equity_usdt"]
                if state_summary["peak_equity_usdt"] is not None
                else ""
            ),
            "fusion_runtime_open_exposure_usdt": str(state_summary["open_exposure_usdt"]),
        }
    )
    payload["metrics"] = metrics
    from hl_observer.runtime.status_freshness import stamp_status_fields

    stamp_status_fields(
        payload,
        ("fusion_runtime_group",),
        producer="fusion_heartbeat_input",
        session_id=str(payload.get("session_id") or ""),
        updated_at_ms=status_updated_at_ms,
    )
    _write_json_atomic(engine_status_path, payload)
    return report


def format_fusion_heartbeat_report(report: FusionHeartbeatBuildReport) -> str:
    return (
        "fusion-heartbeat-input "
        f"status={report.status} "
        f"votes={report.votes_count} "
        f"price_events={report.price_events_count} "
        f"coins={','.join(report.coins) or '-'} "
        f"reasons={','.join(report.reasons) or '-'} "
        f"recent_deltas={report.recent_deltas_count} "
        f"entry_deltas={report.recent_entry_deltas_count} "
        f"latest_delta_age_ms={report.latest_delta_age_ms if report.latest_delta_age_ms is not None else '-'} "
        "paper_only=true real_execution=false"
    )


def _latest_delta_age_ms(session: Session, *, current_ms: int) -> int | None:
    row = (
        session.query(PositionDeltaModel.detected_at_ms)
        .filter(PositionDeltaModel.detected_at_ms.isnot(None))
        .order_by(desc(PositionDeltaModel.detected_at_ms), desc(PositionDeltaModel.id))
        .limit(1)
        .first()
    )
    if row is None:
        return None
    latest_ms = _safe_int(row[0])
    if latest_ms is None:
        return None
    return max(0, int(current_ms) - latest_ms)


def _top_wallet_scores(session: Session) -> dict[str, float]:
    rows = session.query(TopWallet).order_by(desc(TopWallet.score), desc(TopWallet.selected_at_ms)).limit(500).all()
    scores: dict[str, float] = {}
    for row in rows:
        key = str(row.wallet_address or "").lower()
        if key and key not in scores:
            scores[key] = float(row.score or 0.0)
    return scores


def _side_from_delta(delta: PositionDeltaModel) -> str:
    raw_values = " ".join(
        str(value or "")
        for value in (
            delta.action,
            delta.delta_type,
            delta.side,
            delta.new_side,
        )
    ).upper()
    if "LONG" in raw_values:
        return "LONG"
    if "SHORT" in raw_values:
        return "SHORT"
    current = _safe_float(delta.current_size)
    if current is not None:
        if current > 0:
            return "LONG"
        if current < 0:
            return "SHORT"
    return "UNKNOWN"


def _is_entry_action(action: str, delta: PositionDeltaModel) -> bool:
    if action in ENTRY_ACTIONS or any(token in action for token in ("OPEN", "ADD", "INCREASE")):
        return True
    previous = _safe_float(delta.previous_size)
    current = _safe_float(delta.current_size)
    if previous is None or current is None:
        return False
    return abs(current) > abs(previous)


def _vote_score(*, wallet_score: float, confidence: float, notional: float) -> float:
    wallet_component = max(0.25, min(5.0, wallet_score / 20.0))
    confidence_component = max(0.0, min(2.0, confidence / 50.0))
    notional_component = max(0.0, min(3.0, notional / 25_000.0))
    return round(wallet_component + confidence_component + notional_component, 6)


def _distilled_candidate_from_delta(
    delta: PositionDeltaModel,
    *,
    wallet: str,
    coin: str,
    side: str,
    action: str,
    wallet_score: float,
    notional: float,
    current_ms: int,
) -> dict[str, Any] | None:
    """Promote a delta to the distilled detector only when metrics are measured.

    The GitHub-distilled path must not invent edge, liquidity, or copy costs.
    A regular leader vote can still reach the legacy consensus path, but a
    distilled opportunity candidate requires explicit measurements in the
    delta payload produced by upstream analyzers.
    """

    raw = _merged_delta_payload(delta)
    edge_remaining = _first_float(raw, "edge_remaining_bps", "net_edge_bps", "expected_edge_remaining_bps")
    liquidity_score = _first_float(raw, "liquidity_score", "market_liquidity_score", "book_liquidity_score")
    copy_degradation_bps = _first_float(raw, "copy_degradation_bps", "copy_cost_bps", "total_copy_cost_bps")
    if edge_remaining is None or liquidity_score is None or copy_degradation_bps is None:
        return None
    observed_at_ms = _safe_int(raw.get("observed_at_ms")) or _safe_int(raw.get("event_time_ms")) or _safe_int(delta.detected_at_ms) or _safe_int(delta.exchange_ts) or current_ms
    source_profile = (
        str(raw.get("source_profile") or raw.get("strategy_id") or raw.get("profile") or delta.source or "local_db_position_delta")
        .strip()
        or "local_db_position_delta"
    )
    return {
        "wallet": wallet,
        "leader_wallet": wallet,
        "coin": coin,
        "side": side,
        "action_type": action or "UNKNOWN",
        "event_time_ms": int(observed_at_ms),
        "leader_notional_usdc": round(max(0.0, float(notional or 0.0)), 6),
        "edge_remaining_bps": round(float(edge_remaining), 6),
        "liquidity_score": round(max(0.0, min(1.0, float(liquidity_score))), 6),
        "leader_score": round(float(wallet_score or 0.0), 6),
        "copy_degradation_bps": round(max(0.0, float(copy_degradation_bps)), 6),
        "source_profile": source_profile,
        "source_delta_id": int(delta.id or 0),
        "read_only": True,
        "simulation_only": True,
        "external_action": False,
    }


def _merged_delta_payload(delta: PositionDeltaModel) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(delta.proofs_json, dict):
        merged.update(delta.proofs_json)
    if isinstance(delta.raw_json, dict):
        merged.update(delta.raw_json)
    return merged


def _first_float(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _safe_float(payload.get(key))
        if value is not None:
            return value
    return None


def _latest_mids(session: Session) -> tuple[dict[str, float], dict[str, int]]:
    mids: dict[str, float] = {}
    timestamps: dict[str, int] = {}
    snapshots = session.query(MarketSnapshot).order_by(desc(MarketSnapshot.exchange_ts), desc(MarketSnapshot.id)).limit(50).all()
    for snapshot in snapshots:
        raw = snapshot.raw_json or {}
        prices = raw.get("prices") if isinstance(raw, dict) and isinstance(raw.get("prices"), dict) else raw
        if not isinstance(prices, dict):
            continue
        trade_times = raw.get("trade_times_ms") if isinstance(raw, dict) and isinstance(raw.get("trade_times_ms"), dict) else {}
        for raw_coin, raw_price in prices.items():
            coin = str(raw_coin).upper()
            if coin in mids:
                continue
            price = _safe_float(raw_price)
            if price is None or price <= 0:
                continue
            mids[coin] = price
            timestamps[coin] = _safe_int(trade_times.get(raw_coin) if isinstance(trade_times, dict) else None) or _safe_int(snapshot.exchange_ts) or now_ms()
    return mids, timestamps


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_ui_state_summary(path: Path) -> dict[str, Any]:
    payload = _read_json_object(path)
    starting = _safe_float(payload.get("simulation_starting_equity_usdt"))
    realized = _safe_float(payload.get("simulation_realized_pnl_usdc"))
    if starting is None or starting <= 0:
        return {
            "starting_equity_usdt": None,
            "current_equity_usdt": None,
            "peak_equity_usdt": None,
            "open_exposure_usdt": 0.0,
            "source": "missing_session_baseline",
        }
    realized = float(first_not_none(realized, 0.0))
    current = starting + realized
    open_exposure = 0.0
    peak = current
    history = payload.get("simulation_equity_history")
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            equity = _safe_float(item.get("current_equity_usdt"))
            if equity is not None:
                current = equity
                peak = max(peak, equity)
            exposure = _safe_float(item.get("open_exposure_usdt"))
            if exposure is not None:
                open_exposure = exposure
    positions = payload.get("simulation_virtual_positions")
    if isinstance(positions, dict) and positions:
        estimated_exposure = 0.0
        for raw in positions.values():
            if not isinstance(raw, dict):
                continue
            size = abs(float(first_not_none(_safe_float(raw.get("size")), 0.0)))
            price = float(first_not_none(_safe_float(raw.get("avg_price")), 0.0))
            estimated_exposure += size * price
        if estimated_exposure > 0:
            open_exposure = estimated_exposure
    return {
        "starting_equity_usdt": round(float(starting), 6),
        "current_equity_usdt": round(float(current), 6),
        "peak_equity_usdt": round(float(max(peak, current, starting)), 6),
        "open_exposure_usdt": round(float(open_exposure), 6),
        "source": "ui_simulation_state" if payload else "default_no_ui_state",
    }


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


__all__ = [
    "FusionHeartbeatBuildReport",
    "build_fusion_runtime_input_from_session",
    "format_fusion_heartbeat_report",
    "write_fusion_runtime_input_to_engine_status",
]


def _build_funding_rows(coins) -> list:
    """Alimente le detecteur funding-arb depuis le cache de taux (funding_runtime_cache).

    Un coin n'apparait que s'il a de l'historique reel. Vide = etat honnete
    (le poller HYPERSMART_V26_FUNDING_POLLER doit tourner pour remplir le cache).
    Le detecteur applique lui-meme son seuil d'historique (anti-spike).
    """
    # AUDIT 2026-07-08 — TROU CRITIQUE corrigé: le poller n'avait AUCUN point de
    # démarrage sur le chemin live (son seul appel était derrière un autre flag
    # non activé). Sans ça: cache vide -> funding_rows=[] -> funding-arb ne trade
    # JAMAIS. On le démarre ici (idempotent, no-op si HYPERSMART_V26_FUNDING_POLLER
    # n'est pas actif). Le thread daemon remplit le cache pour les heartbeats suivants.
    try:
        from hl_observer.funding.funding_poller import ensure_started as _ensure_funding_poller
        _ensure_funding_poller(None)
    except Exception:
        _noter_echec("hl_observer/runtime/fusion_heartbeat_input.py:580")

    # AUDIT 2026-07-12 -- LE MEME TROU, SUR L'AUTRE POLLER.
    # Le 2026-07-08 on a corrige ce bug pour le funding (commentaire ci-dessus) et on a laisse le
    # poller de CARNET L2 dans l'etat qu'on venait de denoncer : son SEUL point de demarrage etait
    # v26_entry_vetos.apply_v26_entry_vetos, derriere le flag maitre
    # HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE, absent du launcher => False => thread jamais lance.
    # Verifie sur 12 h de run : funding.jsonl grossit (7 Mo), l2_book.jsonl n'existait meme pas.
    # Sans carnet : live_costs_for() ne rend rien, les couts retombent sur des CONSTANTES, et le
    # market making est INTESTABLE. Idempotent ; no-op si HYPERSMART_V26_BOOK_POLLER est off.
    try:
        from hl_observer.collection.l2_snapshot_cache import ensure_started as _ensure_book_poller
        _ensure_book_poller(None)
    except Exception:
        _noter_echec("hl_observer/runtime/fusion_heartbeat_input.py:594")

    try:
        from hl_observer.funding.funding_runtime_cache import recent_rates
    except Exception:
        return []
    rows = []
    for coin in coins or ():
        try:
            rates = recent_rates(str(coin))
        except Exception:
            rates = []
        if rates:
            rows.append({"coin": str(coin).upper(), "rates": list(rates)})
    return rows

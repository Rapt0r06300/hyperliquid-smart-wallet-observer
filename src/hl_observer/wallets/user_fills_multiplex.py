"""V27 — Firehose userFills MULTIPLEXE (un maximum de signaux frais).

Verite mesuree: Hyperliquid cape les abonnements ``userFills`` a 10 wallets PAR
connexion WebSocket. Le runtime actuel ne suit donc en temps reel que le top-10
leaders (le reste tombe sur un scan REST rotatif ~10s -> signaux vieux). Pour avoir
BEAUCOUP plus de signaux frais, on ouvre PLUSIEURS connexions persistantes en
parallele, chacune sur un groupe de <=10 leaders. On couvre ainsi N*10 leaders en
sub-seconde au lieu de 10.

Chaque connexion reutilise ``stream_user_fills_ws`` (deja teste: reconnect/backoff,
garde network-read, snapshot-ignore, store des fills FRAIS). Firehose explicitement
autorise pour la collecte. Lecture seule / paper-only: jamais d'ordre, de signature,
de cle, de depot. Plafond dur anti-ban: on ne depasse JAMAIS ``MAX_CONNECTIONS_HARD``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from hl_observer.collection.collector import WALLET_RE
from hl_observer.config.settings import Settings
from hl_observer.wallets.user_fills_live import StreamStats, stream_user_fills_ws

HL_MAX_WALLETS_PER_CONNECTION = 10       # limite dure Hyperliquid (userFills)
MAX_CONNECTIONS_HARD = 8                  # plafond anti-ban : 8*10 = 80 leaders temps reel


@dataclass(slots=True)
class MultiplexStats:
    connections: int = 0
    wallets_covered: int = 0
    total_connects: int = 0
    total_reconnects: int = 0
    messages_seen: int = 0
    fresh_fills_stored: int = 0
    deltas_stored: int = 0
    snapshots_ignored: int = 0
    stopped_reason: str = "not_started"
    per_connection: list[StreamStats] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def plan_multiplex_chunks(
    wallets: Iterable[str],
    *,
    wallets_per_connection: int = HL_MAX_WALLETS_PER_CONNECTION,
    max_connections: int = 4,
) -> list[list[str]]:
    """Valide + dedoublonne la liste COMPLETE (ordre preserve = priorite du meilleur
    leader), puis decoupe en groupes de <=10 (cap HL), borne par ``max_connections``
    (lui-meme borne par ``MAX_CONNECTIONS_HARD``). Deterministe, pur."""
    wpc = max(1, min(int(wallets_per_connection), HL_MAX_WALLETS_PER_CONNECTION))
    conns = max(1, min(int(max_connections), MAX_CONNECTIONS_HARD))
    limit = wpc * conns
    seen: set[str] = set()
    clean: list[str] = []
    for raw in wallets:
        wallet = str(raw or "").strip()
        if not WALLET_RE.fullmatch(wallet):
            continue
        key = wallet.lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append(key)
        if len(clean) >= limit:
            break
    return [clean[i : i + wpc] for i in range(0, len(clean), wpc)][:conns]


async def stream_user_fills_multiplex(
    settings: Settings,
    *,
    wallets: Iterable[str],
    session_factory: Any,
    network_read: bool = False,
    wallets_per_connection: int = HL_MAX_WALLETS_PER_CONNECTION,
    max_connections: int = 4,
    websocket_connect: Any | None = None,
    stop_event: Any | None = None,
    max_live_fill_age_ms: int = 20_000,
    max_reconnects: int | None = None,
    sleep: Any | None = None,
    connect_timeout_s: float = 15.0,
    recv_timeout_s: float = 30.0,
) -> MultiplexStats:
    """Ouvre jusqu'a ``max_connections`` streams userFills persistants EN PARALLELE
    (chacun <=10 leaders) et agrege leurs stats. Chaque stream stocke ses fills frais
    dans la MEME base -> le copy-run les voit immediatement. Pur transport, read-only."""
    stats = MultiplexStats(stopped_reason="duration_elapsed")
    if not network_read:
        stats.stopped_reason = "NETWORK_READ_DISABLED"
        stats.warnings.append("Network read disabled: multiplex userFills firehose not opened.")
        return stats
    chunks = plan_multiplex_chunks(
        wallets, wallets_per_connection=wallets_per_connection, max_connections=max_connections
    )
    if not chunks:
        stats.stopped_reason = "SOURCE_UNAVAILABLE"
        stats.warnings.append("No complete wallet addresses for multiplex userFills firehose.")
        return stats
    stats.connections = len(chunks)
    stats.wallets_covered = sum(len(chunk) for chunk in chunks)

    async def _one(chunk: list[str]) -> StreamStats:
        return await stream_user_fills_ws(
            settings,
            wallets=chunk,
            session_factory=session_factory,
            max_users=wallets_per_connection,
            network_read=network_read,
            websocket_connect=websocket_connect,
            stop_event=stop_event,
            max_live_fill_age_ms=max_live_fill_age_ms,
            max_reconnects=max_reconnects,
            sleep=sleep,
            connect_timeout_s=connect_timeout_s,
            recv_timeout_s=recv_timeout_s,
        )

    results = await asyncio.gather(*[_one(chunk) for chunk in chunks], return_exceptions=True)
    reasons: set[str] = set()
    for res in results:
        if isinstance(res, BaseException):
            stats.warnings.append(f"connection failed: {res!r}")
            reasons.add("SOURCE_UNAVAILABLE")
            continue
        stats.per_connection.append(res)
        stats.total_connects += res.connects
        stats.total_reconnects += res.reconnects
        stats.messages_seen += res.messages_seen
        stats.fresh_fills_stored += res.fresh_fills_stored
        stats.deltas_stored += res.deltas_stored
        stats.snapshots_ignored += res.snapshots_ignored
        reasons.add(res.stopped_reason)
        stats.warnings.extend(res.warnings)
    if reasons == {"stopped"}:
        stats.stopped_reason = "stopped"
    elif reasons and reasons <= {"SOURCE_UNAVAILABLE"}:
        stats.stopped_reason = "SOURCE_UNAVAILABLE"
    elif "stopped" in reasons:
        stats.stopped_reason = "stopped"
    elif "max_reconnects" in reasons:
        stats.stopped_reason = "max_reconnects"
    return stats


def format_multiplex_report(stats: MultiplexStats) -> str:
    return (
        f"live_user_fills_multiplex connections={stats.connections} "
        f"wallets_covered={stats.wallets_covered} connects={stats.total_connects} "
        f"reconnects={stats.total_reconnects} fresh_fills_stored={stats.fresh_fills_stored} "
        f"deltas_stored={stats.deltas_stored} snapshots_ignored={stats.snapshots_ignored} "
        f"stopped={stats.stopped_reason}"
    )


def _run_cli(argv: list[str] | None = None) -> int:
    """Entrypoint always-on pour le launcher: firehose userFills multiplexe sur les
    meilleurs leaders quality-gated. Meme base + memes settings que le runtime (reutilise
    les helpers CLI). Read-only / paper-only : jamais d'ordre, de signature, de cle."""
    import argparse
    import asyncio as _asyncio
    import threading as _threading
    import time as _time

    parser = argparse.ArgumentParser(
        description="HyperSmart firehose userFills multiplexe (read-only, paper-only)"
    )
    parser.add_argument("--network-read", action="store_true",
                        help="Ouvre le WebSocket public Hyperliquid (lecture seule).")
    parser.add_argument("--max-connections", type=int, default=4,
                        help=f"Connexions WS paralleles (borne dure {MAX_CONNECTIONS_HARD}).")
    parser.add_argument("--wallets-per-connection", type=int, default=HL_MAX_WALLETS_PER_CONNECTION)
    parser.add_argument("--duration-seconds", type=int, default=0,
                        help="0 = toujours actif (moteur temps reel permanent).")
    parser.add_argument("--max-live-fill-age-ms", type=int, default=20000)
    args = parser.parse_args(argv)

    from sqlalchemy import select as _select
    from hl_observer.cli import _apply_leader_quality_gate, _session_factory, _settings
    from hl_observer.storage.models import TopWallet as _TopWallet

    settings = _settings()
    session_factory = _session_factory(settings)
    conns = max(1, min(int(args.max_connections), MAX_CONNECTIONS_HARD))
    wpc = max(1, min(int(args.wallets_per_connection), HL_MAX_WALLETS_PER_CONNECTION))
    pool = conns * wpc
    with session_factory() as session:
        rows = session.scalars(
            _select(_TopWallet).order_by(_TopWallet.score.desc()).limit(max(pool, 50))
        ).all()
        try:
            rows = _apply_leader_quality_gate(session, rows, limit=pool)
        except Exception:
            pass
        wallets = [r.wallet_address for r in rows[:pool] if getattr(r, "wallet_address", None)]
    if not wallets:
        print("live_user_fills_multiplex=no_leaders_available")
        return 0

    stop = _threading.Event()
    deadline = None if args.duration_seconds <= 0 else (_time.time() + float(args.duration_seconds))

    async def _runner() -> MultiplexStats:
        async def _watch() -> None:
            while not stop.is_set():
                if deadline is not None and _time.time() >= deadline:
                    stop.set()
                    return
                await _asyncio.sleep(1.0)

        watcher = _asyncio.ensure_future(_watch())
        try:
            return await stream_user_fills_multiplex(
                settings, wallets=wallets, session_factory=session_factory,
                network_read=bool(args.network_read), max_connections=conns,
                wallets_per_connection=wpc, stop_event=stop,
                max_live_fill_age_ms=int(args.max_live_fill_age_ms),
            )
        finally:
            watcher.cancel()

    stats = _asyncio.run(_runner())
    print(format_multiplex_report(stats))
    print("mode: read-only persistent userFills multiplex; no exchange, no signature, no order")
    return 0


__all__ = [
    "HL_MAX_WALLETS_PER_CONNECTION",
    "MAX_CONNECTIONS_HARD",
    "MultiplexStats",
    "plan_multiplex_chunks",
    "stream_user_fills_multiplex",
    "format_multiplex_report",
]


if __name__ == "__main__":
    raise SystemExit(_run_cli())

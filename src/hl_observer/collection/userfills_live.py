"""FLUX userFills LIVE → snapshots frais (rectif Flo 23/07). Cœur PUR, testable sans réseau.

Au lieu d'attendre un snapshot toutes les 300 s, on met à jour la position d'un vault DÈS chaque fill
WS `userFills` : on SEED depuis le dernier snapshot connu (positions par coin), puis on applique chaque
fill (szi += signe×sz). On émet alors un snapshot FRAIS que la détection existante (signaux_vaults)
consomme immédiatement — l'ouverture devient event-driven, et plusieurs petits OPEN/ADD s'AGRÈGENT
naturellement dans la position. Le collecteur réseau (`tools/collecter_userfills_vaults.py`) n'est que
la boucle WS autour de ces fonctions. Lecture seule. 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import time
from typing import Any

from hl_observer.realtime.event_identity import canonicalize_frame

_EPS = 1e-12


def positions_depuis_snapshot(snap: dict) -> dict[str, dict]:
    """{coin: {szi, entryPx}} depuis un snapshot vault (seed de l'état live)."""
    out: dict[str, dict] = {}
    for p in (snap.get("positions") or []):
        c = str(p.get("coin") or "").upper()
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
    c = str(fill.get("coin") or "").upper()
    if not c:
        return positions
    try:
        sz = abs(float(fill.get("sz") or 0.0))
        signe = int(fill.get("signe") or 0)
        px = float(fill.get("px") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return positions
    if sz <= _EPS or signe not in (-1, 1):
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


def parser_message_userfills(msg: Any, *, vault: str = "", received_at_ms: int | None = None) -> list[dict]:
    """Normalise un message WS userFills en conservant DEUX horloges distinctes.

    ``ts_ms`` vient de l'exchange (fill ``time``). ``received_at_ms`` est l'heure murale locale de
    réception du frame WS, injectée par le collecteur au plus près de ``ws.recv``. Si le cœur est appelé
    seul, elle est capturée une seule fois à l'entrée de cette fonction. On ne remplace JAMAIS la réception
    par le timestamp exchange : cela fabriquerait une latence nulle et détruirait la preuve causale.

    `isSnapshot` est propagé (le snapshot initial rejoue l'historique : à IGNORER pour trader). Tolérant.
    Le champ `liquidation` de WsFill est préservé lorsqu'il existe.
    """
    data = msg.get("data") if isinstance(msg, dict) else None
    fills = (data or {}).get("fills") if isinstance(data, dict) else None
    est_snapshot = bool((data or {}).get("isSnapshot")) if isinstance(data, dict) else False
    sequence_raw = msg.get("sequence", msg.get("seq")) if isinstance(msg, dict) else None
    if sequence_raw is None and isinstance(data, dict):
        sequence_raw = data.get("sequence", data.get("seq"))
    try:
        frame_sequence = int(sequence_raw) if sequence_raw is not None else None
    except (TypeError, ValueError):
        frame_sequence = None
    try:
        frame_received_at_ms = int(received_at_ms) if received_at_ms is not None else int(time.time() * 1_000)
    except (TypeError, ValueError, OverflowError):
        frame_received_at_ms = int(time.time() * 1_000)

    raw_fills = [item for item in (fills or []) if isinstance(item, dict)]
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
        try:
            coin = str(f["coin"]).upper()
            px = float(f["px"])
            sz = abs(float(f["sz"]))
            ts = int(f["time"])
        except (KeyError, TypeError, ValueError):
            continue
        side = str(f.get("side") or "").upper()
        try:
            start_pos = float(f.get("startPosition"))
        except (TypeError, ValueError):
            start_pos = None
        entry = {"vault": vault, "coin": coin, "px": px, "sz": sz,
                 "signe": 1 if side == "B" else (-1 if side == "A" else 0),
                 "ts_ms": ts, "received_at_ms": frame_event.received_at_ms,
                 "dir": str(f.get("dir") or ""), "hash": f.get("hash"),
                 "tid": f.get("tid"), "oid": f.get("oid"),
                 "start_position": start_pos, "isSnapshot": est_snapshot,
                 "source": "LIVE_WS",
                 "frame_sequence": frame_event.frame_sequence,
                 "event_index_in_frame": frame_event.event_index_in_frame,
                 "stable_event_id": frame_event.stable_event_id}
        liq = f.get("liquidation")
        if liq:
            entry["liquidation"] = liq
        out.append(entry)
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
                    "liquidatedUser": liq.get("liquidatedUser"), "markPx": liq.get("markPx"),
                    "method": liq.get("method"), "provenance": "REAL_LIQUIDATION",
                    "source": "userFills.liquidation"})
    return out


__all__ = ["positions_depuis_snapshot", "appliquer_fill", "snapshot_depuis_positions",
           "parser_message_userfills", "liquidations_confirmees"]

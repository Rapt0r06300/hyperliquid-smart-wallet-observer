"""Logs ultra-détaillés, structurés ET BORNÉS (anti-bloat) — run + replay.

Chaque catégorie écrit dans son JSONL capé/rotaté : jamais de croissance infinie
(pas de re-bloat comme les 29 Go). Best-effort absolu : n'échoue JAMAIS, ne casse
jamais le moteur (une erreur de log ne doit pas arrêter le bot).

Catégories: TRADE, DECISION, REFUSAL, POSITION, ERROR, FUNDING, SCAN, SYSTEM.
Chaque ligne : {ts_ms, cat, sev, msg, ...champs}. Replay-ready (coin/side/edge/reason).
Objectif: voir ABSOLUMENT tout — chaque trade, PnL, position, décision, refus, et
chaque erreur même minuscule — sans jamais saturer le disque.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any

_DIRNAME = "logs/detailed"
_MAX_LINES = 20_000            # par fichier ; ~quelques Mo max par catégorie
_MAX_BYTES = 8_000_000
SEV = ("DEBUG", "INFO", "WARN", "ERROR", "CRITICAL")


def _dir(runtime_data_dir: str | Path | None = None) -> Path:
    if runtime_data_dir:
        base = Path(runtime_data_dir)
    else:
        env = os.getenv("HYPERSMART_UI_STATE_DIR", "").strip()
        base = Path(env) if env else Path("runtime/data")
    return base.parent / _DIRNAME if base.name == "data" else base / _DIRNAME


def _path(cat: str, runtime_data_dir=None) -> Path:
    return _dir(runtime_data_dir) / f"{str(cat).lower()}.jsonl"


def _cap(p: Path, max_lines: int) -> None:
    try:
        if p.stat().st_size > _MAX_BYTES:
            lines = p.read_text(encoding="utf-8").splitlines()[-int(max_lines):]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def log(cat: str, msg: str, *, sev: str = "INFO", runtime_data_dir=None, **fields: Any) -> None:
    """Écrit une ligne structurée. Best-effort, ne lève jamais."""
    try:
        d = _dir(runtime_data_dir)
        d.mkdir(parents=True, exist_ok=True)
        row = {"ts_ms": int(time.time() * 1000), "cat": str(cat).upper(),
               "sev": str(sev).upper() if str(sev).upper() in SEV else "INFO", "msg": str(msg)}
        for k, v in fields.items():
            try:
                json.dumps(v)  # ne garder que le sérialisable
                row[k] = v
            except Exception:
                row[k] = str(v)
        p = d / f"{str(cat).lower()}.jsonl"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        _cap(p, _MAX_LINES)
    except Exception:
        pass


def log_trade(action: str, coin: str, side: str, *, net_pnl_usdc: float | None = None,
              notional_usdt: float | None = None, entry_price: float | None = None,
              exit_price: float | None = None, fee_usdc: float | None = None,
              funding_usdc: float | None = None, reason: str | None = None, **extra) -> None:
    log("TRADE", f"{action} {coin} {side}", sev="INFO", action=action, coin=coin, side=side,
        net_pnl_usdc=net_pnl_usdc, notional_usdt=notional_usdt, entry_price=entry_price,
        exit_price=exit_price, fee_usdc=fee_usdc, funding_usdc=funding_usdc, reason=reason, **extra)


def log_decision(coin: str, side: str, decision: str, *, edge_net_bps: float | None = None,
                 reason: str | None = None, strategy: str | None = None, **extra) -> None:
    log("DECISION", f"{decision} {coin} {side}", sev="INFO", coin=coin, side=side,
        decision=decision, edge_net_bps=edge_net_bps, reason=reason, strategy=strategy, **extra)


def log_refusal(coin: str, reason: str, *, edge_net_bps: float | None = None,
                side: str | None = None, **extra) -> None:
    # replay: un refus mesurable (le PnL qu'on aurait fait) est précieux pour l'A/B.
    log("REFUSAL", f"NO_TRADE {coin} : {reason}", sev="INFO", coin=coin, side=side,
        reason=reason, edge_net_bps=edge_net_bps, **extra)


def log_position(coin: str, side: str, *, unrealized_pnl_usdc: float | None = None,
                 notional_usdt: float | None = None, **extra) -> None:
    log("POSITION", f"{coin} {side}", sev="DEBUG", coin=coin, side=side,
        unrealized_pnl_usdc=unrealized_pnl_usdc, notional_usdt=notional_usdt, **extra)


def log_error(where: str, exc: BaseException | str, *, sev: str = "ERROR", **context) -> None:
    """Capture une erreur MÊME MINUSCULE avec contexte + traceback court."""
    if isinstance(exc, BaseException):
        tb = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        trace = "".join(traceback.format_tb(exc.__traceback__))[-800:]
        log("ERROR", f"{where}: {tb}", sev=sev, where=where, error_type=type(exc).__name__,
            error=str(exc)[:400], traceback=trace, **context)
    else:
        log("ERROR", f"{where}: {exc}", sev=sev, where=where, error=str(exc)[:400], **context)


def read(cat: str, *, max: int = 300, runtime_data_dir=None) -> list[dict]:
    """Dernières lignes d'une catégorie (chronologique). [] si vide."""
    try:
        p = _path(cat, runtime_data_dir)
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()
        if max:
            lines = lines[-int(max):]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []


def summary(runtime_data_dir=None) -> dict:
    """Résumé de toutes les catégories: compte + dernière entrée par catégorie."""
    cats = ["trade", "decision", "refusal", "position", "error", "funding", "scan", "system"]
    out: dict[str, Any] = {}
    for c in cats:
        rows = read(c, max=1_000_000 if c == "error" else 5, runtime_data_dir=runtime_data_dir)
        # pour error on compte tout (jusqu'au cap), sinon juste un aperçu
        p = _path(c, runtime_data_dir)
        n = 0
        try:
            n = sum(1 for _ in p.open(encoding="utf-8")) if p.exists() else 0
        except Exception:
            n = len(rows)
        out[c] = {"count": n, "last": rows[-1] if rows else None}
    return out


__all__ = ["log", "log_trade", "log_decision", "log_refusal", "log_position",
           "log_error", "read", "summary"]

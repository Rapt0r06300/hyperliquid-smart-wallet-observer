"""Historique d'equity persisté par le MOTEUR (indépendant du dashboard/Chrome).

Bug corrigé: la courbe d'equity n'était alimentée que par l'endpoint overview
pol_lé par le dashboard → fermer Chrome coupait l'ajout de points → « pas
d'historique » à la réouverture. Ici le runner écrit UN point par poll dans un
JSONL persistant ; ``/v2/equity_history`` le relit → l'historique survit à la
fermeture du navigateur (le moteur, lui, tourne toujours).

Capé (taille bornée) pour ne jamais regonfler. Pur I/O, best-effort (jamais
d'exception propagée : la courbe ne doit pas casser le moteur). Paper-only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from hl_observer.ops.echec_silencieux import noter as _noter_echec
from hl_observer.simulation.accounting_truth import finite_number

FILE_NAME = "equity_history.jsonl"
DEFAULT_MAX_POINTS = 12_000          # ~48h à un point / 15 s ; fichier < 1 Mo
_MAX_BYTES = 3_000_000               # au-delà, on réécrit en gardant les derniers points


def _dir(runtime_data_dir: str | Path | None = None) -> Path:
    if runtime_data_dir:
        return Path(runtime_data_dir)
    env = os.getenv("HYPERSMART_UI_STATE_DIR", "").strip()
    return Path(env) if env else Path("runtime/data")


def _path(runtime_data_dir=None) -> Path:
    return _dir(runtime_data_dir) / FILE_NAME


def append_equity_point(
    *,
    timestamp_ms: int,
    equity_usdt: float,
    pnl_usdc: float | None = None,
    starting_equity_usdt: float | None = None,
    session_id: str | None = None,
    accounting_status: str | None = None,
    runtime_data_dir: str | Path | None = None, max_points: int = DEFAULT_MAX_POINTS,
) -> None:
    """Ajoute un point d'equity sans inventer un PnL ou une baseline."""
    try:
        timestamp = int(timestamp_ms)
        equity = finite_number(equity_usdt)
        pnl = finite_number(pnl_usdc)
        starting = finite_number(starting_equity_usdt)
        if timestamp <= 0 or equity is None:
            return
        d = _dir(runtime_data_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = d / FILE_NAME
        line = json.dumps(
            {
                "t": timestamp,
                "equity": round(equity, 6),
                "pnl": round(pnl, 6) if pnl is not None else None,
                "starting_equity_usdt": (
                    round(starting, 6) if starting is not None and starting > 0 else None
                ),
                "session_id": str(session_id) if session_id else None,
                "accounting_status": str(
                    accounting_status
                    or ("MEASURABLE" if pnl is not None else "BASELINE_UNMEASURABLE")
                ),
            },
            allow_nan=False,
            sort_keys=True,
        )
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        # cap taille (rare): si trop gros, garder les derniers max_points
        try:
            if p.stat().st_size > _MAX_BYTES:
                lines = p.read_text(encoding="utf-8").splitlines()[-int(max_points):]
                p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            _noter_echec("hl_observer/runtime/equity_history_store.py:57")
    except Exception:
        _noter_echec("hl_observer/runtime/equity_history_store.py:59")


def read_equity_points(*, max: int = 600, runtime_data_dir: str | Path | None = None) -> list[dict]:
    """Derniers points persistés (chronologique). [] si aucun (état honnête)."""
    try:
        p = _path(runtime_data_dir)
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()
        if max and len(lines) > int(max):
            lines = lines[-int(max):]
        out: list[dict] = []
        for ln in lines:
            try:
                o = json.loads(ln)
                timestamp = int(o.get("t"))
                equity = finite_number(o.get("equity"))
                pnl = finite_number(o.get("pnl"))
                starting = finite_number(o.get("starting_equity_usdt"))
                if timestamp <= 0 or equity is None:
                    continue
                out.append(
                    {
                        "t": timestamp,
                        "equity": equity,
                        "pnl": pnl,
                        "starting_equity_usdt": starting,
                        "session_id": o.get("session_id"),
                        "accounting_status": str(
                            o.get("accounting_status")
                            or ("MEASURABLE" if pnl is not None else "BASELINE_UNMEASURABLE")
                        ),
                    }
                )
            except Exception:
                continue
        return out
    except Exception:
        return []


__all__ = ["append_equity_point", "read_equity_points", "FILE_NAME"]

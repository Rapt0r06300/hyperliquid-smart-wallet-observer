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
    *, timestamp_ms: int, equity_usdt: float, pnl_usdc: float = 0.0,
    runtime_data_dir: str | Path | None = None, max_points: int = DEFAULT_MAX_POINTS,
) -> None:
    """Ajoute un point {t, equity, pnl} au JSONL persistant (best-effort)."""
    try:
        d = _dir(runtime_data_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = d / FILE_NAME
        line = json.dumps({
            "t": int(timestamp_ms),
            "equity": round(float(equity_usdt), 6),
            "pnl": round(float(pnl_usdc), 6),
        })
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        # cap taille (rare): si trop gros, garder les derniers max_points
        try:
            if p.stat().st_size > _MAX_BYTES:
                lines = p.read_text(encoding="utf-8").splitlines()[-int(max_points):]
                p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass
    except Exception:
        pass


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
                out.append({"t": int(o.get("t") or 0), "equity": float(o.get("equity") or 0.0), "pnl": float(o.get("pnl") or 0.0)})
            except Exception:
                continue
        return out
    except Exception:
        return []


__all__ = ["append_equity_point", "read_equity_points", "FILE_NAME"]

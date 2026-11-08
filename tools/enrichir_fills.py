#!/usr/bin/env python3
"""Enrichissement des fills avec leur CONTEXTE marché — idée #94.

Pour chaque fill, on attache le contexte observé AU PLUS PRÈS (≤ lag causal) :
- **carnet/BBO** le plus proche → mid, spread (bps), slippage du fill vs mid, lag du carnet ;
- **funding** en vigueur → coût de portage ;
- **bougie** récente → volatilité réalisée (high-low / close).

Résultat : des records **auto-suffisants** (`*_enrichi.jsonl`) replayables sans rejointure.
Pur, hors-ligne, borné par `max_lag_ms`. Causalité stricte : on n'utilise QUE du contexte
dont l'horodatage d'observation est ≤ celui du fill + marge (jamais du futur). PAPER / lecture seule.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

RACINE = Path(__file__).resolve().parents[1]

LAG_CARNET_MS = 60_000     # fenêtre d'appariement fill↔carnet (aligné labo MAX_TARGET_LAG_MS)
LAG_FUNDING_MS = 8 * 3_600_000
LAG_CANDLE_MS = 5 * 60_000


def _nb(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _ts_fill(f: dict) -> int | None:
    for k in ("ts_ms", "exchange_ts_ms", "time"):
        v = f.get(k)
        if isinstance(v, int) and v > 0:
            return v
    return None


def _ts_contexte(r: dict) -> int | None:
    for k in ("exchange_ts_ms", "received_at_ms", "observed_at_ms", "ts_ms", "open_ts_ms", "time"):
        v = r.get(k)
        if isinstance(v, int) and v > 0:
            return v
    return None


def construire_index(rows: Iterable[dict], *, ts_getter=_ts_contexte) -> dict[str, Any]:
    """Index {coin: (liste_ts triée, liste_rows alignée)} pour recherche dichotomique."""
    tmp: dict[str, list[tuple[int, dict]]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        coin = r.get("coin")
        ts = ts_getter(r)
        if not coin or ts is None:
            continue
        tmp.setdefault(str(coin), []).append((ts, r))
    index: dict[str, Any] = {}
    for coin, paires in tmp.items():
        paires.sort(key=lambda p: p[0])
        index[coin] = ([p[0] for p in paires], [p[1] for p in paires])
    return index


def plus_proche(index: dict[str, Any], coin: str, ts: int, max_lag_ms: int,
                *, causal: bool = True) -> tuple[dict | None, int | None]:
    """Record le plus proche de `ts` pour `coin`, |Δ| ≤ max_lag_ms. causal=True : pas de futur."""
    entree = index.get(str(coin))
    if not entree:
        return None, None
    ts_list, rows = entree
    i = bisect.bisect_right(ts_list, ts)
    meilleur, best_lag = None, None
    for j in (i - 1, i):   # voisin avant et voisin après
        if 0 <= j < len(ts_list):
            dt = ts_list[j] - ts
            if causal and dt > 0:
                continue        # futur interdit en mode causal (sauf le voisin après si non causal)
            lag = abs(dt)
            if lag <= max_lag_ms and (best_lag is None or lag < best_lag):
                meilleur, best_lag = rows[j], lag
    if meilleur is None and not causal:
        return None, None
    return meilleur, best_lag


def _bbo_mid_spread(r: dict) -> tuple[float | None, float | None]:
    bid, ask = _nb(r.get("bid") or r.get("best_bid")), _nb(r.get("ask") or r.get("best_ask"))
    if bid and ask and ask >= bid > 0:
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 10_000 if mid > 0 else None
        return mid, spread_bps
    return None, None


def enrichir_fill(fill: dict, *, idx_bbo: dict, idx_funding: dict, idx_candle: dict,
                  lag_carnet_ms: int = LAG_CARNET_MS) -> dict:
    """Rend une copie du fill augmentée d'un bloc `contexte`."""
    out = dict(fill)
    ts = _ts_fill(fill)
    px = _nb(fill.get("px") or fill.get("price"))
    ctx: dict[str, Any] = {"apparie_carnet": False}
    if ts is not None:
        bbo, lag = plus_proche(idx_bbo, fill.get("coin"), ts, lag_carnet_ms, causal=True)
        if bbo is not None:
            mid, spread_bps = _bbo_mid_spread(bbo)
            ctx["apparie_carnet"] = mid is not None
            ctx["mid_at_fill"] = mid
            ctx["spread_bps"] = spread_bps
            ctx["book_lag_ms"] = lag
            if mid and px and mid > 0:
                signe = fill.get("signe")
                slip = (px - mid) / mid * 10_000
                ctx["slippage_bps"] = slip if signe not in (-1,) else -slip
        fund, flag = plus_proche(idx_funding, fill.get("coin"), ts, LAG_FUNDING_MS, causal=True)
        if fund is not None:
            ctx["funding_rate"] = _nb(fund.get("funding") or fund.get("fundingRate") or fund.get("rate"))
        candle, _ = plus_proche(idx_candle, fill.get("coin"), ts, LAG_CANDLE_MS, causal=True)
        if candle is not None:
            o, h, l, c = (_nb(candle.get(k)) for k in ("open", "high", "low", "close"))
            if h is not None and l is not None and c and c > 0:
                ctx["realized_vol_bps"] = (h - l) / c * 10_000
    out["contexte"] = ctx
    return out


def _lire_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return []
    return rows


def enrichir(fills_path: Path, out_path: Path, *, bbo_path: Path | None = None,
             funding_path: Path | None = None, candle_path: Path | None = None,
             lag_carnet_ms: int = LAG_CARNET_MS) -> dict[str, Any]:
    fills = _lire_jsonl(fills_path)
    idx_bbo = construire_index(_lire_jsonl(bbo_path)) if bbo_path and bbo_path.exists() else {}
    idx_funding = construire_index(_lire_jsonl(funding_path)) if funding_path and funding_path.exists() else {}
    idx_candle = construire_index(_lire_jsonl(candle_path)) if candle_path and candle_path.exists() else {}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    apparies = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for f in fills:
            e = enrichir_fill(f, idx_bbo=idx_bbo, idx_funding=idx_funding, idx_candle=idx_candle,
                              lag_carnet_ms=lag_carnet_ms)
            if e["contexte"].get("apparie_carnet"):
                apparies += 1
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return {"fills": len(fills), "apparies_carnet": apparies,
            "taux_appariement": round(apparies / len(fills), 4) if fills else 0.0,
            "out": str(out_path)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Enrichit les fills avec leur contexte marche (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--fills", required=True)
    p.add_argument("--bbo", default="")
    p.add_argument("--funding", default="")
    p.add_argument("--candle", default="")
    p.add_argument("--out", default="")
    p.add_argument("--lag-carnet-ms", type=int, default=LAG_CARNET_MS)
    args = p.parse_args(argv)
    root = Path(args.root)

    def _rel(x):
        if not x:
            return None
        pp = Path(x)
        return pp if pp.is_absolute() else root / pp

    fills_path = _rel(args.fills)
    if not fills_path or not fills_path.exists():
        print(f"[enrich] fills introuvables : {fills_path}", flush=True)
        return 0
    out = _rel(args.out) if args.out else fills_path.with_name(fills_path.stem + "_enrichi.jsonl")
    rap = enrichir(fills_path, out, bbo_path=_rel(args.bbo), funding_path=_rel(args.funding),
                   candle_path=_rel(args.candle), lag_carnet_ms=args.lag_carnet_ms)
    print(f"[enrich] {rap['fills']} fills, {rap['apparies_carnet']} appariés à un carnet "
          f"({rap['taux_appariement']*100:.1f}%) -> {rap['out']}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

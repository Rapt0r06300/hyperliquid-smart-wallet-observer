"""Cerveau de l'explorer autonome — décisions intelligentes, fonctions PURES.

L'explorer public d'Hyperliquid diffuse l'activité de TOUS les users (ordres par bloc), mais
les ordres référencent l'actif par INDICE (`a`) et ne donnent pas le fill réel. Ce module :

- `decoder_coin` / `normaliser_ordre` : décode l'indice d'actif en coin via l'univers (meta publique),
  normalise un ordre explorer en intention lisible (coin, sens, px, sz) — étiqueté INTENTION, pas fill ;
- `rang_activite` : classe les users par activité récente → **auto-découverte** de leaders candidats ;
- `inferer_fills` : corrèle les ordres des leaders avec les trades marché publics pour estimer les
  exécutions (coin+temps+prix+sens, budget anti-double-comptage, score de confiance). Résultat
  étiqueté `source="EXPLORER_INFERRED"` + `confidence` — **signal de recherche, jamais certifié SAFE**.

PAPER / lecture seule. Honnêteté : une estimation n'est jamais présentée comme un fill réel certifié.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence

MINUTE_MS = 60_000


def _nb(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def decoder_coin(order: Mapping, univers: Sequence[str]) -> str | None:
    """Indice d'actif `a` -> nom de coin via l'univers ordonné (meta). Repli sur 'coin' si présent."""
    if order.get("coin"):
        return str(order["coin"])
    a = order.get("a")
    if isinstance(a, bool):
        return None
    if isinstance(a, int) and 0 <= a < len(univers):
        return str(univers[a])
    if isinstance(a, str) and a.isdecimal():
        i = int(a)
        if 0 <= i < len(univers):
            return str(univers[i])
    return None


def normaliser_ordre(order: Mapping, univers: Sequence[str], *, user: str, t_ms: int) -> dict | None:
    """Ordre explorer brut -> intention normalisée (coin, signe, px, sz). INTENTION, pas fill."""
    coin = decoder_coin(order, univers)
    px = _nb(order.get("p") or order.get("px"))
    sz = _nb(order.get("s") or order.get("sz"))
    if not coin or px is None or sz is None or px <= 0 or sz <= 0:
        return None
    b = order.get("b")
    if b is None:
        b = order.get("is_buy")
    signe = 1 if b in (True, "true", 1, "1", "b", "B") else -1 if b in (False, "false", 0, "0", "a", "A", "s", "S") else None
    if signe is None:
        return None
    return {"vault": str(user).strip().lower(), "coin": coin, "signe": signe,
            "px_ordre": px, "sz_ordre": sz, "ts_ms": int(t_ms),
            "source": "EXPLORER_ORDER_INTENT"}


def rang_activite(evenements: Iterable[Mapping], *, now_ms: int, demi_vie_min: float = 30.0,
                  exclure: Iterable[str] = ()) -> list[tuple[str, float]]:
    """Classe les users par activité récente pondérée (EWMA) — auto-découverte de candidats."""
    exclus = {str(u).strip().lower() for u in exclure}
    lam = math.log(2) / max(1e-9, demi_vie_min)
    scores: dict[str, float] = {}
    for ev in evenements:
        u = str(ev.get("user") or ev.get("vault") or "").strip().lower()
        if not u or u in exclus:
            continue
        t = ev.get("time") or ev.get("ts_ms")
        if not isinstance(t, (int, float)):
            continue
        age_min = max(0.0, (now_ms - t) / MINUTE_MS)
        scores[u] = scores.get(u, 0.0) + math.exp(-lam * age_min)
    return sorted(scores.items(), key=lambda p: (-p[1], p[0]))


def _index_trades(trades: Iterable[Mapping]):
    par_coin: dict[str, list] = {}
    for tr in trades:
        coin = tr.get("coin")
        ts = tr.get("exchange_ts_ms") or tr.get("ts_ms") or tr.get("time")
        px, sz = _nb(tr.get("px") or tr.get("price")), _nb(tr.get("sz") or tr.get("size"))
        if not coin or not isinstance(ts, (int, float)) or px is None or sz is None or px <= 0 or sz <= 0:
            continue
        ag = str(tr.get("aggressor_side") or tr.get("side") or "").upper()
        signe = 1 if ag.startswith("B") else -1 if ag.startswith(("S", "A")) else 0
        par_coin.setdefault(str(coin), []).append([int(ts), px, sz, signe, sz])  # dernier = budget restant
    for coin in par_coin:
        par_coin[coin].sort(key=lambda r: r[0])
    return par_coin


def inferer_fills(ordres: Sequence[Mapping], trades: Iterable[Mapping], *,
                  fenetre_ms: int = 3_000, tol_prix: float = 0.002,
                  conf_min: float = 0.3) -> list[dict]:
    """Estime les fills exécutés des leaders en corrélant ordres (intention) et trades marché.

    Étiqueté EXPLORER_INFERRED + confidence. Signal de recherche — JAMAIS certifié SAFE.
    """
    idx = _index_trades(trades)
    out: list[dict] = []
    for o in sorted(ordres, key=lambda x: x.get("ts_ms") or 0):
        coin = o.get("coin")
        px_o, sz_o = _nb(o.get("px_ordre") or o.get("px")), _nb(o.get("sz_ordre") or o.get("sz"))
        t = o.get("ts_ms")
        signe = o.get("signe")
        rangee = idx.get(str(coin))
        if not rangee or px_o is None or sz_o is None or not isinstance(t, int) or signe not in (-1, 1):
            continue
        temps = [r[0] for r in rangee]
        lo = bisect.bisect_left(temps, t - fenetre_ms)
        hi = bisect.bisect_right(temps, t + fenetre_ms)
        reste = sz_o
        for j in range(lo, hi):
            tr = rangee[j]
            if reste <= 1e-12 or tr[4] <= 1e-12:
                continue
            dist_px = abs(tr[1] - px_o) / px_o
            if dist_px > tol_prix:
                continue
            if tr[3] != 0 and tr[3] != signe:   # sens marché opposé à l'intention -> moins probable
                continue
            dist_t = abs(tr[0] - t) / max(1, fenetre_ms)
            conf = max(0.0, (1 - dist_px / tol_prix) * (1 - dist_t)) * (1.0 if tr[3] == signe else 0.6)
            if conf < conf_min:
                continue
            pris = min(reste, tr[4])
            tr[4] -= pris
            reste -= pris
            out.append({"vault": o.get("vault"), "coin": str(coin), "px": tr[1], "sz": pris,
                        "signe": signe, "ts_ms": tr[0], "observed_at_ms": tr[0],
                        "source": "EXPLORER_INFERRED", "confidence": round(conf, 3),
                        "is_snapshot": False, "certifie": False})
    return out

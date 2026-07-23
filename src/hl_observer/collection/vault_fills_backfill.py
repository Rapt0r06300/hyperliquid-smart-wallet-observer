"""BACKFILL DES FILLS DE VAULTS + reconstruction d'ÉPISODES (rectif Flo 23/07).

POURQUOI
--------
Un Δszi lu entre deux snapshots (300 s) est CONTAMINÉ : il peut venir d'un RETRAIT du vault (qui réduit
toutes les positions au pro-rata), pas d'une décision alpha. La vérité, ce sont les FILLS réels
(`userFillsByTime`, endpoint PUBLIC). On les backfill, on reconstruit le cycle de vie par coin
(OPEN/ADD/REDUCE/CLOSE), et on ISOLE les entrées ALPHA (OPEN/ADD sur UN coin) des réductions de retrait
(REDUCE pro-rata SIMULTANÉ sur plusieurs coins). Seules les entrées alpha ont un edge à mesurer.

Ce module est PUR (parsing, pagination, reconstruction, couverture) → testable sans réseau. Le CLI
`tools/backfill_vault_fills.py` fait les appels (lecture seule). Aucun ordre, aucune clé, aucune signature.
"""
from __future__ import annotations

from typing import Any

MS_PAR_HEURE = 3_600_000


# ─────────────────────────────── pagination ───────────────────────────────

def plan_de_requetes(start_ms: int, end_ms: int, *, fenetre_ms: int = 24 * MS_PAR_HEURE) -> list[tuple[int, int]]:
    """Découpe [start,end] en fenêtres `userFillsByTime` (l'endpoint plafonne à ~2000 fills/appel).
    On MESURERA la couverture obtenue, on ne la promet pas."""
    if start_ms >= end_ms:
        return []
    out: list[tuple[int, int]] = []
    t = int(start_ms)
    while t < end_ms:
        out.append((t, min(t + fenetre_ms, int(end_ms))))
        t += fenetre_ms
    return out


# ─────────────────────────────── parsing ───────────────────────────────

def parser_fills(rep: Any, *, vault: str = "") -> list[dict]:
    """Normalise une réponse userFills(ByTime) → fills propres. Champs HL : time, coin, px, sz, side
    ('B'/'A'), dir ('Open Long'/'Close Short'/…), startPosition, oid, hash. Illisible → ignoré."""
    out: list[dict] = []
    for f in (rep or []):
        try:
            coin = str(f["coin"]).upper()
            px = float(f["px"])
            sz = abs(float(f["sz"]))
            ts = int(f["time"])
        except (KeyError, TypeError, ValueError):
            continue
        side = str(f.get("side") or "").upper()                    # 'B' = achat, 'A' = vente
        signe = 1 if side == "B" else (-1 if side == "A" else 0)
        try:
            start_pos = float(f.get("startPosition"))
        except (TypeError, ValueError):
            start_pos = None
        out.append({"vault": vault, "ts_ms": ts, "coin": coin, "px": px, "sz": sz, "signe": signe,
                    "dir": str(f.get("dir") or ""), "start_position": start_pos,
                    "oid": f.get("oid"), "hash": f.get("hash")})
    return out


def dedupliquer(fills: list[dict]) -> list[dict]:
    """Dédup stable par (vault, ts, coin, px, sz, dir, oid/hash) — un backfill paginé recouvre les bords."""
    vus: set[tuple] = set()
    out: list[dict] = []
    for f in sorted(fills, key=lambda x: (x.get("ts_ms", 0), str(x.get("coin")))):
        cle = (f.get("vault"), f.get("ts_ms"), f.get("coin"), f.get("px"), f.get("sz"),
               f.get("dir"), f.get("oid") or f.get("hash"))
        if cle not in vus:
            vus.add(cle)
            out.append(f)
    return out


# ─────────────────────────────── reconstruction du cycle de vie ───────────────────────────────

def reconstruire_episodes(fills: list[dict]) -> list[dict]:
    """Rejoue les fills PAR (vault, coin) pour reconstruire OPEN/ADD/REDUCE/CLOSE. Rend une liste
    d'ÉVÉNEMENTS : {ts, vault, coin, action, direction, taille_usd, pos_avant, pos_apres}. La position
    signée est suivie fill par fill ; `startPosition` recale si présent (robuste aux trous de backfill)."""
    par: dict[tuple[str, str], list[dict]] = {}
    for f in fills:
        par.setdefault((f.get("vault", ""), f["coin"]), []).append(f)
    events: list[dict] = []
    for (vault, coin), fs in par.items():
        fs.sort(key=lambda x: x["ts_ms"])
        pos = None
        for f in fs:
            if pos is None:
                pos = f["start_position"] if f["start_position"] is not None else 0.0
            avant = pos
            pos = avant + f["signe"] * f["sz"]
            taille_usd = f["sz"] * f["px"]
            if abs(avant) < 1e-12:
                action = "OPEN"
            elif (avant > 0) == (f["signe"] > 0):
                action = "ADD"                                     # renforce dans le même sens
            elif abs(pos) < 1e-9:
                action = "CLOSE"
            elif (avant > 0) != (pos > 0):
                action = "CLOSE"                                   # flip -> on clôt (le ré-open sera le fill suivant)
            else:
                action = "REDUCE"
            direction = 1 if (pos if abs(pos) > 1e-12 else avant) > 0 else -1
            events.append({"ts_ms": f["ts_ms"], "vault": vault, "coin": coin, "action": action,
                           "direction": direction, "taille_usd": round(taille_usd, 2),
                           "pos_avant": round(avant, 8), "pos_apres": round(pos, 8), "px": f["px"]})
    events.sort(key=lambda e: e["ts_ms"])
    return events


def marquer_retraits(events: list[dict], *, fenetre_ms: int = 5_000, min_coins: int = 3,
                     tol_frac: float = 0.25) -> list[dict]:
    """Marque `retrait_probable=True` les REDUCE/CLOSE qui font partie d'un déleveraging PRO-RATA
    SIMULTANÉ (>= `min_coins` coins réduits dans la même fenêtre de temps) : signature d'un RETRAIT du
    vault, pas d'une décision alpha. Les entrées OPEN/ADD ne sont jamais des retraits. En place."""
    reduces = [e for e in events if e["action"] in ("REDUCE", "CLOSE")]
    reduces.sort(key=lambda e: e["ts_ms"])
    i = 0
    for e in events:
        e["retrait_probable"] = False
    # regroupe les réductions par grappe temporelle
    n = len(reduces)
    while i < n:
        j = i
        while j + 1 < n and reduces[j + 1]["ts_ms"] - reduces[i]["ts_ms"] <= fenetre_ms:
            j += 1
        grappe = reduces[i:j + 1]
        coins = {e["coin"] for e in grappe}
        if len(coins) >= min_coins:                               # plusieurs coins réduits ensemble = retrait pro-rata
            fracs = [abs(e["pos_avant"] - e["pos_apres"]) / abs(e["pos_avant"]) if e["pos_avant"] else 0.0
                     for e in grappe]
            moy = sum(fracs) / len(fracs) if fracs else 0.0
            if moy > 0 and all(abs(fr - moy) <= tol_frac for fr in fracs):   # réductions de fraction similaire
                for e in grappe:
                    e["retrait_probable"] = True
        i = j + 1
    return events


def entrees_alpha(events: list[dict]) -> list[dict]:
    """Les ÉVÉNEMENTS copiables : OPEN/ADD qui ne sont pas des retraits. C'est la matière de l'edge."""
    return [e for e in events if e["action"] in ("OPEN", "ADD") and not e.get("retrait_probable")]


# ─────────────────────────────── couverture (mesurée, pas promise) ───────────────────────────────

def couverture(fills: list[dict]) -> dict:
    """Couverture RÉELLE du backfill : nb fills, span temporel, coins, par vault. On la constate."""
    if not fills:
        return {"n_fills": 0, "span_h": 0.0, "coins": [], "n_vaults": 0}
    ts = [f["ts_ms"] for f in fills]
    par_vault: dict[str, int] = {}
    for f in fills:
        par_vault[f.get("vault", "")] = par_vault.get(f.get("vault", ""), 0) + 1
    return {"n_fills": len(fills), "span_h": round((max(ts) - min(ts)) / MS_PAR_HEURE, 2),
            "coins": sorted({f["coin"] for f in fills}), "n_vaults": len(par_vault),
            "fills_par_vault": par_vault, "t0_ms": min(ts), "t1_ms": max(ts)}


__all__ = ["plan_de_requetes", "parser_fills", "dedupliquer", "reconstruire_episodes",
           "marquer_retraits", "entrees_alpha", "couverture", "MS_PAR_HEURE"]

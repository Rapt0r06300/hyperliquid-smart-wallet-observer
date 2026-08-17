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

import hashlib
import json
from typing import Any

MS_PAR_HEURE = 3_600_000


def normaliser_vault(vault: Any) -> str:
    """Identité stable et source-indépendante d'un wallet/vault Hyperliquid."""
    return str(vault or "").strip().lower()


# ─────────────────────────────── pagination ───────────────────────────────

def plan_de_requetes(start_ms: int, end_ms: int, *, fenetre_ms: int = 24 * MS_PAR_HEURE) -> list[tuple[int, int]]:
    """Découpe [start,end] en fenêtres `userFillsByTime`.

    Le CLI raffine ensuite adaptativement toute fenêtre qui atteint le cap de
    l'endpoint ; cette fonction ne promet donc jamais qu'une fenêtre de 24 h
    est complète à elle seule.
    """
    if start_ms >= end_ms:
        return []
    if fenetre_ms <= 0:
        raise ValueError("fenetre_ms doit etre > 0")
    out: list[tuple[int, int]] = []
    t = int(start_ms)
    while t < end_ms:
        suivant = min(t + int(fenetre_ms), int(end_ms))
        out.append((t, suivant))
        t = suivant
    return out


# ─────────────────────────────── parsing ───────────────────────────────

def parser_fills(rep: Any, *, vault: str = "") -> list[dict]:
    """Normalise une réponse userFills(ByTime) → fills propres. Champs HL : time, coin, px, sz, side
    ('B'/'A'), dir ('Open Long'/'Close Short'/…), startPosition, oid, hash. Illisible → ignoré."""
    out: list[dict] = []
    vault_id = str(vault or "").strip()
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
        out.append({"vault": vault_id, "ts_ms": ts, "coin": coin, "px": px, "sz": sz, "signe": signe,
                    "dir": str(f.get("dir") or ""), "start_position": start_pos,
                    "tid": f.get("tid"), "oid": f.get("oid"), "hash": f.get("hash")})
    return out


def fill_identity(fill: dict) -> tuple:
    """Return one source-independent identity for a leader fill."""

    event_ref = (
        fill.get("hash")
        or fill.get("tid")
        or fill.get("oid")
        or fill.get("stable_event_id")
        or ""
    )
    return (
        normaliser_vault(fill.get("vault")),
        int(fill.get("ts_ms") or 0),
        str(fill.get("coin") or "").upper(),
        float(fill.get("px") or 0.0),
        float(fill.get("sz") or 0.0),
        str(fill.get("dir") or ""),
        str(event_ref),
    )


def _preuve_fill_score(fill: dict) -> tuple[int, int, int]:
    """Préférence déterministe pour conserver la meilleure preuve d'un doublon.

    Un même fill peut arriver du REST puis du WS (ou l'inverse). L'ordre de
    lecture ne doit jamais décider si la preuve causale LIVE est conservée.
    """
    source = str(fill.get("source") or "").upper()
    live = source == "LIVE_WS"
    causal_live = False
    try:
        ts_ms = int(fill.get("ts_ms") or 0)
        received_at_ms = int(fill.get("received_at_ms") or 0)
        causal_live = live and fill.get("isSnapshot") is False and received_at_ms >= ts_ms > 0
    except (TypeError, ValueError, OverflowError):
        causal_live = False
    refs = sum(fill.get(name) not in (None, "") for name in ("hash", "tid", "oid", "stable_event_id"))
    return (1 if causal_live else 0, 1 if live else 0, refs)


def dedupliquer(fills: list[dict]) -> list[dict]:
    """Dédup source-indépendante ; conserve la preuve causale la plus forte.

    Les bords de pagination et la fusion REST/WS peuvent contenir le même
    événement. Le résultat est identique quel que soit l'ordre des sources.
    """
    par_cle: dict[tuple, dict] = {}
    scores: dict[tuple, tuple[int, int, int]] = {}
    for f in fills:
        cle = fill_identity(f)
        score = _preuve_fill_score(f)
        if cle not in par_cle or score > scores[cle]:
            copie = dict(f)
            par_cle[cle] = copie
            scores[cle] = score
    return sorted(
        par_cle.values(),
        key=lambda x: (
            int(x.get("ts_ms") or 0),
            str(x.get("coin") or ""),
            repr(fill_identity(x)),
        ),
    )


# ─────────────────────────────── reconstruction du cycle de vie ───────────────────────────────

def _fill_id(fill: dict, *, vault: str, coin: str) -> str:
    identity = {
        "vault": vault, "ts_ms": int(fill["ts_ms"]), "coin": coin,
        "px": float(fill["px"]), "sz": float(fill["sz"]),
        "dir": str(fill.get("dir") or ""), "tid": fill.get("tid"),
        "oid": fill.get("oid"), "hash": fill.get("hash"),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _event_id(fill_id: str, *, component_index: int, action: str, pos_avant: float, pos_apres: float) -> str:
    material = {
        "fill_id": fill_id,
        "component_index": int(component_index),
        "action": action,
        "pos_avant": round(float(pos_avant), 12),
        "pos_apres": round(float(pos_apres), 12),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def reconstruire_episodes(fills: list[dict]) -> list[dict]:
    """Rejoue les fills PAR (vault, coin) et reconstruit OPEN/ADD/REDUCE/CLOSE.

    `startPosition`, lorsqu'il est présent, recale CHAQUE fill : un trou de
    backfill ne contamine donc pas tous les événements suivants. Un fill qui
    traverse zéro est décomposé en deux composants économiques du même fill :
    CLOSE de l'ancienne position puis OPEN du reliquat opposé. Aucun reliquat
    n'est perdu silencieusement.
    """
    par: dict[tuple[str, str], list[dict]] = {}
    for f in fills:
        vault = normaliser_vault(f.get("vault"))
        coin = str(f["coin"]).upper()
        copie = dict(f)
        copie["vault"] = vault
        copie["coin"] = coin
        par.setdefault((vault, coin), []).append(copie)

    events: list[dict] = []
    for (vault, coin), fs in par.items():
        fs.sort(key=lambda x: (int(x["ts_ms"]), repr(fill_identity(x))))
        pos: float | None = None
        for f in fs:
            try:
                start_position = float(f["start_position"]) if f.get("start_position") is not None else None
            except (TypeError, ValueError, OverflowError):
                start_position = None
            calcule = 0.0 if pos is None else float(pos)
            avant = start_position if start_position is not None else calcule
            position_rebased = (
                pos is not None
                and start_position is not None
                and abs(start_position - calcule) > 1e-9
            )
            delta = float(f.get("signe") or 0) * float(f["sz"])
            apres = avant + delta
            fill_id = _fill_id(f, vault=vault, coin=coin)

            def ajouter(
                *,
                action: str,
                component_index: int,
                component_count: int,
                composant_avant: float,
                composant_apres: float,
                component_sz: float,
                direction: int,
                dir_label: str | None = None,
            ) -> None:
                taille_usd = abs(float(component_sz)) * float(f["px"])
                raw_snapshot = f.get("isSnapshot")
                label = str(dir_label if dir_label is not None else (f.get("dir") or ""))
                events.append({
                    "ts_ms": f["ts_ms"], "vault": vault, "coin": coin, "action": action,
                    "direction": int(direction), "taille_usd": round(taille_usd, 2),
                    "pos_avant": round(composant_avant, 8), "pos_apres": round(composant_apres, 8),
                    "px": f["px"], "sz": abs(float(component_sz)), "dir": label,
                    "leader_dir": f.get("dir"), "tid": f.get("tid"),
                    "oid": f.get("oid"), "hash": f.get("hash"), "fill_id": fill_id,
                    "event_id": _event_id(
                        fill_id,
                        component_index=component_index,
                        action=action,
                        pos_avant=composant_avant,
                        pos_apres=composant_apres,
                    ),
                    "fill_component_index": int(component_index),
                    "fill_component_count": int(component_count),
                    "position_rebased": bool(position_rebased),
                    "source": f.get("source") or "REST_BACKFILL",
                    "is_snapshot": raw_snapshot if isinstance(raw_snapshot, bool) else None,
                    "observed_at_ms": f.get("received_at_ms"),
                    "stable_event_id": f.get("stable_event_id"),
                })

            eps = 1e-9
            if abs(delta) < eps:
                # Un side illisible ne doit pas fabriquer un événement économique.
                pos = apres
                continue
            if abs(avant) < eps:
                direction = 1 if apres > 0 else -1
                ajouter(
                    action="OPEN", component_index=0, component_count=1,
                    composant_avant=0.0, composant_apres=apres,
                    component_sz=abs(apres), direction=direction,
                )
            elif (avant > 0) == (delta > 0):
                direction = 1 if apres > 0 else -1
                ajouter(
                    action="ADD", component_index=0, component_count=1,
                    composant_avant=avant, composant_apres=apres,
                    component_sz=abs(delta), direction=direction,
                )
            elif abs(apres) < eps:
                direction = 1 if avant > 0 else -1
                ajouter(
                    action="CLOSE", component_index=0, component_count=1,
                    composant_avant=avant, composant_apres=0.0,
                    component_sz=abs(avant), direction=direction,
                )
            elif (avant > 0) == (apres > 0):
                direction = 1 if avant > 0 else -1
                ajouter(
                    action="REDUCE", component_index=0, component_count=1,
                    composant_avant=avant, composant_apres=apres,
                    component_sz=abs(delta), direction=direction,
                )
            else:
                # Flip en un seul fill : CLOSE ancien sens + OPEN du reliquat.
                ancienne_direction = 1 if avant > 0 else -1
                nouvelle_direction = 1 if apres > 0 else -1
                ajouter(
                    action="CLOSE", component_index=0, component_count=2,
                    composant_avant=avant, composant_apres=0.0,
                    component_sz=abs(avant), direction=ancienne_direction,
                    dir_label="Close Long" if ancienne_direction > 0 else "Close Short",
                )
                ajouter(
                    action="OPEN", component_index=1, component_count=2,
                    composant_avant=0.0, composant_apres=apres,
                    component_sz=abs(apres), direction=nouvelle_direction,
                    dir_label="Open Long" if nouvelle_direction > 0 else "Open Short",
                )
            pos = apres

    events.sort(key=lambda e: (int(e["ts_ms"]), str(e["fill_id"]), int(e["fill_component_index"]), str(e["event_id"])))
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
        e.setdefault("retrait_probable", False)                   # n'EFFACE pas une marque déjà posée (ex. ledger)
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
        vault = normaliser_vault(f.get("vault"))
        par_vault[vault] = par_vault.get(vault, 0) + 1
    return {"n_fills": len(fills), "span_h": round((max(ts) - min(ts)) / MS_PAR_HEURE, 2),
            "coins": sorted({f["coin"] for f in fills}), "n_vaults": len(par_vault),
            "fills_par_vault": par_vault, "t0_ms": min(ts), "t1_ms": max(ts)}


CAP_USERFILLS = 10_000            # userFillsByTime plafonne aux ~10k fills RÉCENTS (limite officielle)


def auditer_couverture(fills: list[dict], *, cap: int = CAP_USERFILLS, lookback_debut_ms: int | None = None,
                       coins_tape: set[str] | None = None) -> dict:
    """Audit HONNÊTE de couverture/troncature par vault : n fills, span réel, plus
    ancien/récent, et TRONCATURE probable si le vault a atteint le cap OU si son plus ancien fill est
    bien postérieur au début demandé. `coins_tape` = coins avec prix (candles) → part des coins
    réellement mesurables. On ne PROMET jamais 14 j : on constate."""
    par: dict[str, list[int]] = {}
    coins_fills: set[str] = set()
    for f in fills:
        par.setdefault(normaliser_vault(f.get("vault")), []).append(int(f["ts_ms"]))
        coins_fills.add(str(f.get("coin") or "").upper())
    vaults = []
    for v, ts in par.items():
        ts.sort()
        tronque = len(ts) >= cap
        if lookback_debut_ms is not None and ts and (ts[0] - lookback_debut_ms) > 12 * MS_PAR_HEURE:
            tronque = True
        vaults.append({"vault": v, "n_fills": len(ts), "t0_ms": ts[0] if ts else None,
                       "t1_ms": ts[-1] if ts else None,
                       "span_h": round((ts[-1] - ts[0]) / MS_PAR_HEURE, 1) if len(ts) >= 2 else 0.0,
                       "tronque_probable": bool(tronque)})
    vaults.sort(key=lambda x: -x["n_fills"])
    coins_mesurables = sorted(coins_fills & coins_tape) if coins_tape else []
    return {"n_vaults": len(vaults), "n_fills": len(fills), "n_coins_fills": len(coins_fills),
            "n_coins_mesurables": len(coins_mesurables), "coins_mesurables": coins_mesurables,
            "n_vaults_tronques": sum(1 for v in vaults if v["tronque_probable"]),
            "part_coins_avec_prix": round(len(coins_mesurables) / len(coins_fills), 3) if coins_fills else 0.0,
            "par_vault": vaults}


__all__ = ["plan_de_requetes", "parser_fills", "normaliser_vault", "fill_identity", "dedupliquer",
           "reconstruire_episodes", "marquer_retraits", "entrees_alpha", "couverture", "auditer_couverture",
           "CAP_USERFILLS", "MS_PAR_HEURE"]

"""P5.1 (§7) — score d'ANTICIPATION Wallet×Binance : le wallet agit-il AVANT le mouvement, ou le suit-il ?

Correction majeure : la DIRECTION économique d'une action = f(action, position_side), pas une table
ambiguë. Fermer/réduire un SHORT est un ACHAT (pas une vente) ; fermer/réduire un LONG est une VENTE.
On s'appuie sur la sémantique de `position_lifecycle.LifecycleAction` (OPEN_LONG/OPEN_SHORT/CLOSE_LONG/
CLOSE_SHORT/REDUCE/…). Un `FLIP` est ambigu → `UNMEASURABLE` (il doit être scindé).

Pour une action à l'instant T, on mesure sur le chemin de prix Binance, à plusieurs horizons (100 ms→30 s) :

    move_before = rendement orienté sur [T−h, T]   (ce qui a DÉJÀ bougé avant l'action)
    move_after  = rendement orienté sur [T, T+h]   (ce qui bouge APRÈS l'action)
    anticipation = move_after − move_before          (haut = leader ; ≤0 = suiveur)

« Orienté » = signé selon la direction économique (achat → hausse favorable ; vente → baisse favorable).
Garde-fous : (1) tolérance temporelle PAR horizon — un prix trop vieux pour l'horizon = UNMEASURABLE,
pas de mesure sur feed trop grossier ; (2) déduplication par event_id/tid/oid — 1 doublon ≠ 2 obs ;
(3) N brut ET N clusterisé (réutilise `scoring_robuste.cle_grappe`) ; (4) sélection stricte
DISCOVERY→RANK→FREEZE→OOS INTACT (réutilise `scoring_robuste.separer_decouverte_validation`), jamais
choisir et valider un wallet sur la même fenêtre. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.following.scoring_robuste import cle_grappe, separer_decouverte_validation

SCHEMA_VERSION = "hypersmart.binance_anticipation.v2"

#: Horizons réellement observables (ms).
HORIZONS_MS = (100, 250, 500, 1_000, 2_000, 5_000, 10_000, 30_000)
#: Tolérance temporelle par horizon : un snapshot doit être frais à ± max(TOL_MIN, TOL_FRACTION·h).
TOL_MIN_MS = 50.0
TOL_FRACTION = 0.5

_LONG = ("LONG", "L", "BUY", "B", "1", "+1")
_SHORT = ("SHORT", "S", "SELL", "-1")


def direction_economique(action: object, position_side: object = None) -> int | None:
    """Direction économique RÉELLE : +1 achat, −1 vente, `None` si ambigu. `f(action, position_side)`.

    Règle clé : fermer/réduire un SHORT = ACHAT ; fermer/réduire un LONG = VENTE. `FLIP`/inconnu = None."""
    a = str(action or "").strip().upper()
    side = str(position_side or "").strip().upper()
    long_side = side in _LONG
    short_side = side in _SHORT

    # Actions qui ENCODENT déjà le sens de position.
    if a == "OPEN_LONG":
        return 1
    if a == "OPEN_SHORT":
        return -1
    if a == "CLOSE_LONG":
        return -1                     # fermer un long = vendre
    if a == "CLOSE_SHORT":
        return 1                      # fermer un short = acheter

    # Ouvertures/renforts génériques : suivent le position_side.
    if a in ("OPEN", "ADD", "INCREASE"):
        if long_side:
            return 1
        if short_side:
            return -1
        return None
    # Réductions/fermetures génériques + liquidation : OPPOSÉ au position_side.
    if a in ("REDUCE", "CLOSE", "LIQUIDATION"):
        if long_side:
            return -1                 # réduire/fermer un long = vendre
        if short_side:
            return 1                  # réduire/fermer un short = acheter
        return None
    # Direction de fill brute.
    if a in ("BUY", "B", "BID"):
        return 1
    if a in ("SELL", "ASK"):
        return -1
    if a == "S" and not long_side:
        return -1
    return None                       # FLIP, UNKNOWN, ou side manquant → ambigu


def _pt(x: object) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _cle_dedup(ev: Mapping[str, Any]) -> str:
    """Clé de dédup : event_id, sinon tid, sinon oid, sinon empreinte causale (wallet,coin,ts,action)."""
    for k in ("event_id", "tid", "oid"):
        v = ev.get(k)
        if v not in (None, "", 0, "0"):
            return f"{k}:{v}"
    return "emp:%s:%s:%s:%s" % (ev.get("wallet"), ev.get("coin"), ev.get("ts_ms"), ev.get("action"))


def dedup_evenements(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Déduplique par event_id/tid/oid (1 doublon ≠ 2 observations). Garde la première occurrence."""
    vus: set[str] = set()
    out: list[dict[str, Any]] = []
    for ev in events or ():
        k = _cle_dedup(ev)
        if k not in vus:
            vus.add(k)
            out.append(dict(ev))
    return out


def _tol(h: float, tol_fraction: float, tol_min_ms: float) -> float:
    return max(float(tol_min_ms), float(tol_fraction) * float(h))


def _normaliser_chemin(path: Sequence[Any]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in path or ():
        if isinstance(p, Mapping):
            ts, px = _pt(p.get("ts_ms")), _pt(p.get("price"))
        else:
            try:
                ts, px = _pt(p[0]), _pt(p[1])
            except (TypeError, IndexError):
                ts = px = None
        if ts is not None and px is not None and px > 0:
            out.append((ts, px))
    out.sort(key=lambda kv: kv[0])
    return out


def _prix_a(chemin: list[tuple[float, float]], t: float, tol: float) -> float | None:
    """Prix causal à `t` (dernier ≤ t) SEULEMENT s'il est frais à ± tol de `t` ; sinon `None` (trop vieux)."""
    prix = None
    ts_prix = None
    for ts, px in chemin:
        if ts <= t:
            prix, ts_prix = px, ts
        else:
            break
    if prix is None or ts_prix is None:
        return None
    return prix if (t - ts_prix) <= tol else None


def _rendement_bps(p0: float, p1: float) -> float:
    return (p1 / p0 - 1.0) * 10_000.0


def score_anticipation(
    *,
    t_event_ms: float,
    action: object,
    position_side: object = None,
    path: Sequence[Any],
    horizons_ms: Sequence[int] = HORIZONS_MS,
    tol_fraction: float = TOL_FRACTION,
    tol_min_ms: float = TOL_MIN_MS,
) -> dict[str, Any]:
    """Anticipation par horizon, orientée par la direction économique, avec tolérance temporelle par horizon."""
    chemin = _normaliser_chemin(path)
    sens = direction_economique(action, position_side)
    t = _pt(t_event_ms)
    par_horizon: dict[int, Any] = {}
    mesurables: list[float] = []

    for h in horizons_ms:
        h = int(h)
        if not chemin or t is None or sens is None:
            par_horizon[h] = {"statut": "UNMEASURABLE"}
            continue
        tol = _tol(h, tol_fraction, tol_min_ms)
        p_before = _prix_a(chemin, t - h, tol)
        p_now = _prix_a(chemin, t, tol)
        p_after = _prix_a(chemin, t + h, tol)
        if p_now is None or p_before is None or p_after is None:
            par_horizon[h] = {"statut": "UNMEASURABLE"}
            continue
        mb = sens * _rendement_bps(p_before, p_now)
        ma = sens * _rendement_bps(p_now, p_after)
        antici = ma - mb
        par_horizon[h] = {"statut": "MEASURED", "move_before_bps": round(mb, 6),
                          "move_after_bps": round(ma, 6), "anticipation_bps": round(antici, 6)}
        mesurables.append(antici)

    return {
        "schema_version": SCHEMA_VERSION,
        "sens": sens,
        "par_horizon": par_horizon,
        "n_horizons_mesures": len(mesurables),
        "anticipation_moy_bps": (round(sum(mesurables) / len(mesurables), 6) if mesurables else None),
        "real_execution": False,
    }


def _mediane(vals: Sequence[float]) -> float | None:
    v = sorted(vals)
    n = len(v)
    if n == 0:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def anticipation_par_wallet(
    evenements: Sequence[Mapping[str, Any]],
    path_par_coin: Mapping[str, Sequence[Any]],
    *,
    horizon_ms: int = 1_000,
) -> dict[str, Any]:
    """Anticipation médiane par wallet à un horizon, avec dédup et N brut + N clusterisé (mesure seulement)."""
    events = dedup_evenements(evenements)
    par_wallet_vals: dict[str, list[float]] = {}
    par_wallet_ev: dict[str, list[Mapping[str, Any]]] = {}
    for ev in events:
        wallet = str(ev.get("wallet") or "")
        coin = str(ev.get("coin") or "").upper()
        if not wallet or coin not in path_par_coin:
            continue
        s = score_anticipation(t_event_ms=ev.get("ts_ms"), action=ev.get("action"),
                               position_side=ev.get("position_side"),
                               path=path_par_coin[coin], horizons_ms=(horizon_ms,))
        cell = s["par_horizon"].get(int(horizon_ms), {})
        if cell.get("statut") == "MEASURED":
            par_wallet_vals.setdefault(wallet, []).append(cell["anticipation_bps"])
            par_wallet_ev.setdefault(wallet, []).append(ev)

    resultats = {}
    for wallet, vals in par_wallet_vals.items():
        grappes = {cle_grappe(e) for e in par_wallet_ev[wallet]}
        resultats[wallet] = {
            "n_raw": len(vals),                       # observations brutes (dédupliquées)
            "n_clustered": len(grappes),              # observations INDÉPENDANTES (metaorder/burst/wcj)
            "anticipation_mediane_bps": round(_mediane(vals), 6),
        }
    return {"schema_version": SCHEMA_VERSION, "horizon_ms": int(horizon_ms),
            "wallets": resultats, "real_execution": False}


def selection_freeze_oos(
    evenements: Sequence[Mapping[str, Any]],
    path_par_coin: Mapping[str, Sequence[Any]],
    *,
    horizon_ms: int = 1_000,
    fraction_decouverte: float = 0.6,
    top_k: int = 5,
    min_clusters: int = 2,
) -> dict[str, Any]:
    """DISCOVERY→RANK→FREEZE→OOS INTACT. On classe les wallets sur la DÉCOUVERTE, on GÈLE le top-K, puis on
    mesure ces MÊMES wallets gelés sur la VALIDATION disjointe. Le score qui compte est l'OOS, jamais la découverte."""
    events = dedup_evenements(evenements)
    split = separer_decouverte_validation(events, fraction_decouverte=fraction_decouverte)
    dec, val = split.get("decouverte", []), split.get("validation", [])

    scores_dec = anticipation_par_wallet(dec, path_par_coin, horizon_ms=horizon_ms)["wallets"]
    candidats = [(w, d["anticipation_mediane_bps"]) for w, d in scores_dec.items()
                 if d["n_clustered"] >= int(min_clusters)]
    candidats.sort(key=lambda kv: kv[1], reverse=True)
    geles = [w for w, _ in candidats[:int(top_k)]]

    scores_oos_all = anticipation_par_wallet(val, path_par_coin, horizon_ms=horizon_ms)["wallets"]
    oos = {w: scores_oos_all.get(w) for w in geles}      # UNIQUEMENT les wallets gelés, sur la validation intacte

    return {
        "schema_version": SCHEMA_VERSION,
        "horizon_ms": int(horizon_ms),
        "fenetres_disjointes": bool(split.get("disjointes", False)),
        "n_decouverte": len(dec), "n_validation": len(val),
        "classement_decouverte": [{"wallet": w, "anticipation_mediane_bps": s} for w, s in candidats],
        "wallets_geles": geles,
        "oos_wallets_geles": oos,
        "note": "score final = OOS des wallets GELÉS ; jamais la fenêtre de découverte",
        "real_execution": False,
    }


__all__ = [
    "SCHEMA_VERSION", "HORIZONS_MS", "direction_economique", "dedup_evenements",
    "score_anticipation", "anticipation_par_wallet", "selection_freeze_oos",
]

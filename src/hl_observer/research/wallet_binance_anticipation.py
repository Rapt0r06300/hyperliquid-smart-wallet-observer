"""ALPHA P2 — Wallet × Binance ANTICIPATION : quels wallets AGISSENT AVANT Binance ?

Hypothèse : un wallet informé bouge AVANT que Binance (le meneur du marché) ne bouge. On mesure, autour de
chaque fill du wallet, la trajectoire du **mid Binance** :

  * `move_before` = variation Binance sur [T−Δ, T] signée par le sens du fill → si grande & positive, le
    wallet SUIT un mouvement déjà arrivé sur Binance → **FOLLOWER = KILL** ;
  * `move_after`  = variation Binance sur [T, T+Δ] signée → si positive, Binance bouge DANS le sens du wallet
    APRÈS son fill → le wallet **ANTICIPE** (potentiel edge copyable, si > coûts et capturable au signal age).

Edge d'anticipation = `move_after` (partie future) ; pénalité de suiveur = `move_before`. On agrège par
grappe indépendante (wallet:coin:jour, machinerie maison) et on ne valide JAMAIS sur la fenêtre de découverte.

Causalité : `move_after` n'utilise que du futur strict ; les horizons sous la cadence réelle du tape sortent
`UNMEASURABLE` (jamais 0). Coûts déduits pour le verdict tradable. Pur, 0 réseau, 0 ordre réel.
Entrées : bbo_synchro (`ts_ms, coin, bin_mid`) + fills (`adresse, coin, side, ts_ms`).
"""
from __future__ import annotations

import bisect
import json
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.following.scoring_robuste import agreger_en_grappes, borne_basse_confiance

UNMEASURABLE = "UNMEASURABLE"
HORIZONS_MS_DEFAUT = (500, 1000, 2000, 5000, 10000, 30000)


def charger_bin_series(bbo_path: str, coins: set[str], *, max_lignes: int | None = None) -> dict[str, Any]:
    """Streame bbo_synchro → {coin: (liste_ts triée, liste_bin_mid alignée)}. `max_lignes` borne la lecture."""
    tmp: dict[str, list[tuple[int, float]]] = {c: [] for c in coins}
    n = 0
    with open(bbo_path, encoding="utf-8") as f:
        for line in f:
            if max_lignes is not None and n >= max_lignes:
                break
            n += 1
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            c = d.get("coin")
            if c in tmp:
                t = d.get("ts_ms"); m = d.get("bin_mid")
                if isinstance(t, (int, float)) and isinstance(m, (int, float)) and m > 0:
                    tmp[c].append((int(t), float(m)))
    out: dict[str, Any] = {}
    for c, rows in tmp.items():
        rows.sort(key=lambda r: r[0])
        out[c] = ([r[0] for r in rows], [r[1] for r in rows])
    return out


def _idx_ref(ts_list: Sequence[int], t: int, *, tol_ms: int) -> int | None:
    """Point de RÉFÉRENCE causal à l'instant t : dernier point ≤ t (prix en vigueur), None si trop vieux
    (> tol_ms). Pour m0 au fill : jamais de look-ahead au-delà de T."""
    if not ts_list:
        return None
    i = bisect.bisect_right(ts_list, t) - 1
    if i < 0 or (t - ts_list[i]) > tol_ms:
        return None
    return i


def _idx_proche(ts_list: Sequence[int], t_cible: int, *, tol_ms: int) -> int | None:
    """FIX-16 : index du point le PLUS PROCHE de `t_cible` (avant OU après), None si le plus proche est à
    plus de `tol_ms`. Corrige le biais « dernier ≤ T+h » qui pouvait renvoyer un point vieux de plusieurs
    secondes et l'appeler « prix à l'horizon exact » : on cherche AUTOUR de la cible, tolérance bornée."""
    if not ts_list:
        return None
    i = bisect.bisect_left(ts_list, t_cible)
    best: int | None = None
    best_d: int | None = None
    for j in (i - 1, i):
        if 0 <= j < len(ts_list):
            d = abs(int(ts_list[j]) - t_cible)
            if best_d is None or d < best_d:
                best_d, best = d, j
    if best is None or best_d is None or best_d > tol_ms:
        return None
    return best


def _tol_horizon(h: int, tol_ms: int) -> int:
    """Tolérance bornée pour matcher T±h (FIX-16) : ≤ tol_ms (résolution attendue du tape) ET ≤ h/2 (jamais
    élargir la fenêtre au point de mesurer un autre horizon). Empêche « point à h ms de la cible = horizon »."""
    return max(1, min(tol_ms, h // 2))


def anticipation_fill(serie: tuple[Sequence[int], Sequence[float]], fill: Mapping[str, Any], *,
                      horizons_ms: Sequence[int], tol_ms: int = 1000) -> dict[int, dict[str, float | None]]:
    """Pour un fill, move_before/after Binance signés par sens, à chaque horizon (None si non mesurable).

    Référence m0 = dernier mid ≤ T (causal, pas de look-ahead). Points d'horizon T−h / T+h = mid le PLUS
    PROCHE de la cible dans une tolérance BORNÉE (FIX-16) — jamais un point stale de plusieurs secondes
    rebaptisé « horizon exact ». `before`/`after` exigent un point strictement antérieur/postérieur à la
    référence T — sinon le mouvement serait 0 fabriqué (horizon sous la cadence du tape) → UNMEASURABLE.
    """
    ts_list, mid_list = serie
    T = int(fill["ts_ms"])
    sens = 1.0 if str(fill.get("side", "")).upper() == "LONG" else -1.0
    i0 = _idx_ref(ts_list, T, tol_ms=tol_ms)
    res: dict[int, dict[str, float | None]] = {}
    if i0 is None:
        return {h: {"before": None, "after": None} for h in horizons_ms}
    m0 = mid_list[i0]
    t0 = ts_list[i0]
    for h in horizons_ms:
        tol_h = _tol_horizon(h, tol_ms)
        ib = _idx_proche(ts_list, T - h, tol_ms=tol_h)
        ia = _idx_proche(ts_list, T + h, tol_ms=tol_h)
        before = (sens * (m0 / mid_list[ib] - 1.0) * 1e4) if (ib is not None and ts_list[ib] < t0) else None
        after = (sens * (mid_list[ia] / m0 - 1.0) * 1e4) if (ia is not None and ts_list[ia] > t0) else None
        res[h] = {"before": (round(before, 4) if before is not None else None),
                  "after": (round(after, 4) if after is not None else None)}
    return res


def experience_anticipation(fills: Sequence[Mapping[str, Any]], bin_by_coin: Mapping[str, Any], *,
                            horizon_ms: int = 5000, cout_bps: float = 9.0, tol_ms: int = 1000,
                            min_fills_wallet: int = 8) -> dict[str, Any]:
    """Par wallet : move_before/after moyens (votes indépendants), classification follower/anticipateur, verdict.

    Verdict (à `horizon_ms`) : FOLLOWER si before domine ; sinon anticipation nette = after − coût, jugée par
    LCB sur votes indépendants (grappes). Trop peu de votes → MORE_DATA.
    """
    par_wallet: dict[str, list[dict[str, Any]]] = {}
    for fl in fills:
        c = fl.get("coin")
        if c not in bin_by_coin:
            continue
        a = anticipation_fill(bin_by_coin[c], fl, horizons_ms=(horizon_ms,), tol_ms=tol_ms)[horizon_ms]
        if a["after"] is None:
            continue
        par_wallet.setdefault(str(fl.get("adresse")), []).append({
            "wallet": str(fl.get("adresse")), "coin": c, "ts_ms": fl.get("ts_ms"),
            "before_bps": a["before"], "after_bps": a["after"],
            "net_bps": a["after"] - float(cout_bps),
        })

    lignes: list[dict[str, Any]] = []
    for adr, eps in par_wallet.items():
        if len(eps) < min_fills_wallet:
            continue
        votes_after = agreger_en_grappes(eps, cle_valeur="after_bps")["votes_bps"]
        votes_net = agreger_en_grappes(eps, cle_valeur="net_bps")["votes_bps"]
        befs = [e["before_bps"] for e in eps if e["before_bps"] is not None]
        after_moy = round(sum(votes_after) / len(votes_after), 4) if votes_after else None
        before_moy = round(sum(befs) / len(befs), 4) if befs else None
        lcb_net = borne_basse_confiance(votes_net) if votes_net else None
        follower = (before_moy is not None and after_moy is not None and before_moy >= max(after_moy, 0.0))
        if len(votes_net) < 8 or lcb_net is None:
            verdict = "MORE_DATA"
        elif follower:
            verdict = "KILL_FOLLOWER"
        elif lcb_net <= 0:
            verdict = "KILL"
        else:
            verdict = "ANTICIPATEUR_A_FORWARD"
        lignes.append({"wallet": adr, "n_raw": len(eps), "n_independent": len(votes_net),
                       "move_before_bps": before_moy, "move_after_bps": after_moy,
                       "net_after_cout_bps": (round(after_moy - cout_bps, 4) if after_moy is not None else None),
                       "lcb_net_bps": lcb_net, "follower": follower, "verdict": verdict})
    rang = {"ANTICIPATEUR_A_FORWARD": 0, "MORE_DATA": 1, "KILL": 2, "KILL_FOLLOWER": 3}
    lignes.sort(key=lambda l: (rang.get(l["verdict"], 9), -(l["lcb_net_bps"] or -1e9)))
    return {"horizon_ms": horizon_ms, "cout_bps": cout_bps, "n_wallets_mesures": len(lignes),
            "classement": lignes, "real_execution": False}


def charger_fills(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("adresse") and d.get("coin") and d.get("side") and d.get("ts_ms"):
                out.append(d)
    return out


__all__ = ["charger_bin_series", "anticipation_fill", "experience_anticipation", "charger_fills",
           "HORIZONS_MS_DEFAUT", "UNMEASURABLE"]

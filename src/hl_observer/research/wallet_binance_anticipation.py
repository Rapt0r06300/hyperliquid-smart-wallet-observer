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

from hl_observer.following.scoring_robuste import (
    agreger_en_grappes, borne_basse_confiance, separer_decouverte_validation)

UNMEASURABLE = "UNMEASURABLE"
HORIZONS_MS_DEFAUT = (500, 1000, 2000, 5000, 10000, 30000)

# FIX-17 — vocabulaire lifecycle : le sens BUY/SELL dépend de l'ACTION × position_side, PAS du seul side.
_ACTIONS_OPEN = {"OPEN", "ADD", "INCREASE", "ENTRY", "ENTER", "LONG_OPEN", "SHORT_OPEN"}
_ACTIONS_CLOSE = {"CLOSE", "REDUCE", "DECREASE", "EXIT", "COVER", "TRIM"}
_ACTIONS_FLIP = {"FLIP", "REVERSE"}


def direction_trade(fill: Mapping[str, Any]) -> float | None:
    """FIX-17 — direction MARCHÉ signée d'un fill : +1.0 = BUY (achat), −1.0 = SELL (vente), None si indéterminable.

    Le sens ne se déduit PAS du seul position_side : **fermer/réduire un SHORT est un ACHAT** (rachat), fermer/
    réduire un LONG est une VENTE. Priorité des sources (la plus fiable d'abord) :
      1. `dir`/`direction` texte Hyperliquid : « Open Long »/« Close Short » = BUY ; « Open Short »/« Close Long »
         = SELL ; « Long > Short » = SELL (flip), « Short > Long » = BUY ;
      2. `side` trade explicite : b/buy/bid = BUY ; a/s/sell/ask = SELL ;
      3. (`action` lifecycle OPEN/ADD/REDUCE/CLOSE/FLIP) × `position_side` : OPEN long=BUY, OPEN short=SELL,
         CLOSE long=SELL, CLOSE short=BUY, FLIP→côté résultant (long=BUY net, short=SELL net) ;
      4. rétro-compat : `side` = long/short SANS lifecycle → OPEN implicite (long=BUY, short=SELL).
    Conforme à la convention canonique de `normalization/fills._signed_delta`.
    """
    txt = str(fill.get("dir") or fill.get("direction") or "").strip().lower()
    if txt:
        if "open long" in txt or "close short" in txt:
            return 1.0
        if "open short" in txt or "close long" in txt:
            return -1.0
        if "long" in txt and "short" in txt:                 # flip « long > short » / « short > long »
            return -1.0 if txt.find("long") < txt.find("short") else 1.0
    st = str(fill.get("side") or "").strip().lower()
    if st in {"b", "buy", "bid"}:
        return 1.0
    if st in {"a", "s", "sell", "ask"}:
        return -1.0
    action = str(fill.get("action") or fill.get("lifecycle") or "").strip().upper()
    pos = str(fill.get("position_side") or "").strip().lower()
    if not pos and st in {"long", "short"}:
        pos = st                                             # schéma research : `side` porte le position_side
    if pos in {"long", "short"}:
        long_pos = pos == "long"
        if action in _ACTIONS_CLOSE:
            return -1.0 if long_pos else 1.0                 # FIX-17 : close/reduce SHORT=BUY, LONG=SELL
        # OPEN / FLIP-vers-côté-résultant / (pas de lifecycle → OPEN implicite) : long=BUY, short=SELL
        return 1.0 if long_pos else -1.0
    return None


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
    sens = direction_trade(fill)                              # FIX-17 : BUY/SELL réel (lifecycle × position_side)
    i0 = _idx_ref(ts_list, T, tol_ms=tol_ms)
    res: dict[int, dict[str, float | None]] = {}
    if sens is None or i0 is None:                            # direction indéterminable → jamais un sens fabriqué
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
                            min_fills_wallet: int = 8, fraction_decouverte: float = 0.6) -> dict[str, Any]:
    """Par wallet : move_before/after (votes indépendants), classification follower/anticipateur, verdict OOS.

    FIX-20 — discipline DÉCOUVERTE → FREEZE → OOS (jamais de retune) : on repère l'anticipation sur la fenêtre
    de DÉCOUVERTE (première fraction temporelle) puis on EXIGE que l'edge net survive sur la fenêtre OOS
    DISJOINTE (le reste). Le verdict et la LCB reportés sont ceux de l'OOS — l'edge mesuré sur les données qui
    ont servi à repérer le wallet serait circulaire. FOLLOWER (before domine) = KILL. Peu de votes OOS → MORE_DATA.
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
        befs = [e["before_bps"] for e in eps if e["before_bps"] is not None]
        after_moy = _moy(agreger_en_grappes(eps, cle_valeur="after_bps")["votes_bps"])
        before_moy = round(sum(befs) / len(befs), 4) if befs else None
        follower = (before_moy is not None and after_moy is not None and before_moy >= max(after_moy, 0.0))
        # FIX-20 : coupe temporelle disjointe ; on repère en découverte, on valide en OOS.
        sep = separer_decouverte_validation(eps, fraction_decouverte=fraction_decouverte)
        votes_dec = agreger_en_grappes(sep["decouverte"], cle_valeur="net_bps")["votes_bps"]
        votes_oos = agreger_en_grappes(sep["validation"], cle_valeur="net_bps")["votes_bps"]
        lcb_dec = borne_basse_confiance(votes_dec) if votes_dec else None
        lcb_oos = borne_basse_confiance(votes_oos) if votes_oos else None
        if follower:
            verdict = "KILL_FOLLOWER"
        elif len(votes_oos) < 8 or lcb_oos is None or lcb_dec is None:
            verdict = "MORE_DATA"                              # pas de quoi valider hors-échantillon
        elif lcb_dec <= 0:
            verdict = "KILL"                                   # aucun edge même en découverte
        elif lcb_oos <= 0:
            verdict = "KILL"                                   # edge repéré mais NE SURVIT PAS en OOS (snooping)
        else:
            verdict = "ANTICIPATEUR_A_FORWARD"                 # positif en découverte ET confirmé en OOS
        lignes.append({"wallet": adr, "n_raw": len(eps), "n_independent": len(votes_oos),
                       "move_before_bps": before_moy, "move_after_bps": after_moy,
                       "net_after_cout_bps": (round(after_moy - cout_bps, 4) if after_moy is not None else None),
                       "lcb_net_bps": lcb_oos, "lcb_decouverte_bps": lcb_dec,
                       "votes_net_oos": [round(float(v), 4) for v in votes_oos],   # FIX-34 : distribution pf/es
                       "follower": follower, "verdict": verdict})
    rang = {"ANTICIPATEUR_A_FORWARD": 0, "MORE_DATA": 1, "KILL": 2, "KILL_FOLLOWER": 3}
    lignes.sort(key=lambda l: (rang.get(l["verdict"], 9), -(l["lcb_net_bps"] or -1e9)))
    return {"horizon_ms": horizon_ms, "cout_bps": cout_bps, "n_wallets_mesures": len(lignes),
            "classement": lignes, "real_execution": False}


def _moy(xs: Sequence[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def cle_dedup_fill(d: Mapping[str, Any]) -> str:
    """FIX-18 — clé de déduplication d'un fill : un identifiant d'événement stable prime (event_id/fill_hash/
    tid/oid) ; à défaut, empreinte (adresse, coin, sens, ts_ms, prix/taille). Un même fill rejoué (firehose,
    reconnexion WS, backfill qui recouvre) NE compte qu'UNE fois — sinon N indépendant est artificiellement gonflé."""
    for k in ("event_id", "fill_hash", "hash", "tid", "oid"):
        v = d.get(k)
        if v not in (None, "", 0, "0"):
            return "%s:%s" % (k, v)
    px = d.get("px", d.get("price", d.get("mid_at_fill")))
    sz = d.get("sz", d.get("size"))
    return "raw:%s:%s:%s:%s:%s:%s" % (d.get("adresse"), d.get("coin"), d.get("side"),
                                      d.get("ts_ms"), px, sz)


def charger_fills(path: str) -> list[dict[str, Any]]:
    """Charge les fills (JSONL) en DÉDUPLIQUANT par identité d'événement (FIX-18). Ordre d'arrivée préservé."""
    out: list[dict[str, Any]] = []
    vus: set[str] = set()
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
                k = cle_dedup_fill(d)
                if k in vus:
                    continue                                   # fill déjà vu → jamais recompté
                vus.add(k)
                out.append(d)
    return out


__all__ = ["charger_bin_series", "anticipation_fill", "experience_anticipation", "charger_fills",
           "cle_dedup_fill", "direction_trade", "HORIZONS_MS_DEFAUT", "UNMEASURABLE"]

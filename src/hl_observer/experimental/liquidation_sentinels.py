"""LIQUIDATION_SENTINELS_V2 — cœur PUR, causal, testable sans réseau. 0 ordre, 0 clé, 0 signature.

CAUSALITÉ (règle dure, Flo 25/07) : l'entrée paper d'un fade de liquidation LIVE est la PREMIÈRE cotation HL
reçue STRICTEMENT APRÈS recv + latence pré-enregistrée. JAMAIS « la cotation la plus proche ±2 s », JAMAIS une
cotation antérieure (ce serait du look-ahead). Les liquidations trouvées ENSUITE par REST restent DESCRIPTIVES /
OOS : elles ne peuvent pas déclencher une position rétroactive (`source == "REST_BACKFILL"` -> jamais causale).

CLOCHE : la liquidation (collecteur userFills) et la BBO (collecteur bbo) sont DEUX PROCESSUS -> pas d'horloge
monotone commune. La jointure causale se fait donc sur l'horloge WALL commune (`ts_wall_ms`) + latence ; le
`recv_mono_ns` est conservé pour la provenance/latence INTRA-processus, pas pour comparer deux processus.

EXÉCUTION (5–10 $) : BBO accepté SEULEMENT si la taille au touch couvre >= 2x le notional ; sinon L2/VWAP top
niveaux (si profondeur fournie) ; sinon NON_MESURABLE. Frais RÉELS (userFees), spread réel, slippage, latence.
"""
from __future__ import annotations

import collections
import statistics
from bisect import bisect_right

HORIZONS_S = (1, 3, 5, 15, 30, 60, 120)
LATENCE_MS_DEFAUT = 400.0                 # latence pipeline pré-enregistrée (WS->décision->cotation)
FENETRE_ENTREE_MAX_MS = 3000.0            # au-delà, pas de cotation causale fraîche -> NON_MESURABLE
FEE_AR_BPS_DEFAUT = 9.0                   # frais A/R par défaut (surchargé par userFees réels)
TOUCH_MULT = 2.0                          # BBO exécutable si taille au touch >= 2x le notional


# ─────────────────────────────── 1. SENTINELLES (accélérer les événements) ───────────────────────────────

def selectionner_sentinelles(recs: list[dict], *, k: int = 3) -> dict:
    """Classe les vaults par nb d'ÉPISODES uniques (coin+hash) où ils étaient LIQUIDATEURS
    (liquidatedUser != vault). Rend {sentinelles:[...], par_vault:{...}, n_episodes}. Pur."""
    epis = {}
    for r in recs:
        cle = (r.get("coin"), r.get("hash"))
        if cle not in epis:
            epis[cle] = r
    liq = collections.Counter()
    for r in epis.values():
        v = str(r.get("vault") or "").lower()
        lu = str(r.get("liquidatedUser") or "").lower()
        if v and lu and lu != v:
            liq[r["vault"]] += 1
    top = [v for v, _ in liq.most_common(k)]
    return {"sentinelles": top, "par_vault": dict(liq.most_common()), "n_episodes": len(epis)}


# ─────────────────────────────── 2. ENTRÉE CAUSALE (jamais de look-ahead) ───────────────────────────────

def entree_causale(recv_wall_ms: float, serie, *, latence_ms: float = LATENCE_MS_DEFAUT,
                   fenetre_max_ms: float = FENETRE_ENTREE_MAX_MS):
    """PREMIÈRE cotation HL STRICTEMENT APRÈS recv_wall_ms + latence (jamais la plus proche, jamais antérieure).
    `serie` = ([ts_wall_ms triés], [(bid, ask, bid_sz_usd, ask_sz_usd)]). None si aucune cotation dans la
    fenêtre [recv+latence ; recv+latence+fenetre_max]. Rend (ts, bid, ask, bid_sz, ask_sz)."""
    temps, quotes = serie
    if not temps:
        return None
    seuil = recv_wall_ms + latence_ms
    i = bisect_right(temps, seuil)                 # 1er index STRICTEMENT > seuil (donc APRÈS, jamais avant)
    if i >= len(temps):
        return None
    if temps[i] - seuil > fenetre_max_ms:          # trop loin après -> pas de cotation causale fraîche
        return None
    b, a, bsz, asz = quotes[i]
    return (temps[i], b, a, bsz, asz)


# ─────────────────────────────── 3. EXÉCUTION RÉELLE (≥2x touch, sinon NON_MESURABLE) ───────────────────────────────

def execution_bps(entree, sortie, *, sens: int, notional_usd: float, fee_ar_bps: float = FEE_AR_BPS_DEFAUT,
                  slippage_bps: float = 1.0, touch_mult: float = TOUCH_MULT) -> dict:
    """Net bps d'un fade au bid/ask RÉEL. `entree`/`sortie` = (ts, bid, ask, bid_sz_usd, ask_sz_usd).
    sens +1 = fade long (achat ask entrée, vente bid sortie) ; −1 = short. BBO accepté SEULEMENT si la taille
    au touch (côté payé) >= touch_mult × notional ; sinon NON_MESURABLE (faute de L2/VWAP top-niveaux fournis)."""
    _, e_bid, e_ask, e_bsz, e_asz = entree
    _, s_bid, s_ask, s_bsz, s_asz = sortie
    touch_entree = e_asz if sens > 0 else e_bsz    # on paie l'ask (long) ou le bid (short) à l'entrée
    if touch_entree < touch_mult * notional_usd:
        return {"statut": "NON_MESURABLE", "motif": "TOUCH_INSUFFISANT",
                "touch_usd": round(touch_entree, 1), "requis_usd": round(touch_mult * notional_usd, 1)}
    if sens > 0:
        brut = (s_bid - e_ask) / e_ask * 1e4       # achat ask -> vente bid
    else:
        brut = (e_bid - s_ask) / e_bid * 1e4       # vente bid -> rachat ask
    spread_bps = (e_ask - e_bid) / (0.5 * (e_ask + e_bid)) * 1e4
    net = brut - fee_ar_bps - slippage_bps
    return {"statut": "OK", "net_bps": round(net, 3), "brut_bps": round(brut, 3),
            "spread_reel_bps": round(spread_bps, 3), "touch_usd": round(touch_entree, 1)}


def est_causal(ev: dict) -> bool:
    """Deny-by-default : un épisode n'est causal QUE s'il vient du live (`source == "LIVE_WS"`) ET porte
    `recv_wall_ms`. Tout backfill REST, tout enregistrement legacy sans horloge de réception -> NON causal
    (descriptif/OOS) : il ne peut jamais déclencher une position rétroactive."""
    return ev.get("source") == "LIVE_WS" and ev.get("recv_wall_ms") is not None


def mesurer_episode(ev: dict, serie, *, latence_ms: float = LATENCE_MS_DEFAUT, notional_usd: float = 8.0,
                    fee_ar_bps: float = FEE_AR_BPS_DEFAUT) -> dict:
    """Un épisode de liquidation LIVE -> net causal aux 7 horizons. `ev` = {coin, recv_wall_ms, sens, source}.
    Non-LIVE_WS (REST/legacy) -> DESCRIPTIF (jamais causal). sens : forced sell (long liquidé) -> fade long (+1)."""
    if not est_causal(ev):
        return {"statut": "OOS_DESCRIPTIF", "coin": ev.get("coin"), "motif": "NON_CAUSAL_" + str(ev.get("source") or "SANS_SOURCE")}
    e = entree_causale(ev["recv_wall_ms"], serie, latence_ms=latence_ms)
    if e is None:
        return {"statut": "NON_MESURABLE", "motif": "AUCUNE_COTATION_CAUSALE", "coin": ev.get("coin")}
    sens = ev["sens"]
    par_h = {}
    for h in HORIZONS_S:
        s = entree_causale(e[0] + h * 1000 - latence_ms, serie, latence_ms=latence_ms, fenetre_max_ms=FENETRE_ENTREE_MAX_MS)
        if s is None:
            par_h[str(h)] = {"statut": "NON_MESURABLE"}
            continue
        par_h[str(h)] = execution_bps(e, s, sens=sens, notional_usd=notional_usd, fee_ar_bps=fee_ar_bps)
    return {"statut": "OK", "coin": ev.get("coin"), "recv_wall_ms": ev["recv_wall_ms"],
            "entree_ts_ms": e[0], "latence_ms": latence_ms, "sens": sens, "par_horizon": par_h}


# ─────────────────────────────── 4. DÉCISION (armer/shadow) ───────────────────────────────

def _pf(nets):
    pos = sum(x for x in nets if x > 0)
    neg = sum(-x for x in nets if x < 0)
    return round(pos / neg, 3) if neg > 0 else (float("inf") if pos > 0 else 0.0)


def _drawdown(nets):
    cum = 0.0
    pic = 0.0
    dd = 0.0
    for x in nets:
        cum += x
        pic = max(pic, cum)
        dd = min(dd, cum - pic)
    return round(dd, 2)


def decision(episodes: list[dict], *, horizon_ref: int = 30, min_episodes: int = 10, min_par_moitie: int = 5) -> dict:
    """Armable SEULEMENT si : >= 10 épisodes LIVE causaux OK ; >= 5 par moitié temporelle ; net médian > 0
    dans LES DEUX moitiés ; ET net médian global > 0 SANS le meilleur épisode (leave-one-out)."""
    ok = [e for e in episodes if e.get("statut") == "OK"
          and e["par_horizon"].get(str(horizon_ref), {}).get("statut") == "OK"]
    nets = [e["par_horizon"][str(horizon_ref)]["net_bps"] for e in ok]
    n = len(nets)
    if n < min_episodes:
        return {"armable": False, "motif": "PAS_ASSEZ_D_EPISODES_LIVE_CAUSAUX", "n": n, "requis": min_episodes,
                "net_median": (round(statistics.median(nets), 3) if nets else None), "pf": _pf(nets), "dd_bps": _drawdown(nets)}
    tri = sorted(ok, key=lambda e: e["recv_wall_ms"])
    m = n // 2
    n1 = [e["par_horizon"][str(horizon_ref)]["net_bps"] for e in tri[:m]]
    n2 = [e["par_horizon"][str(horizon_ref)]["net_bps"] for e in tri[m:]]
    med1 = statistics.median(n1) if len(n1) >= min_par_moitie else None
    med2 = statistics.median(n2) if len(n2) >= min_par_moitie else None
    meilleur = max(range(n), key=lambda i: nets[i])
    sans_meilleur = [x for i, x in enumerate(nets) if i != meilleur]
    med_loo = statistics.median(sans_meilleur) if sans_meilleur else None
    armable = bool(med1 is not None and med2 is not None and med1 > 0 and med2 > 0 and (med_loo or -1) > 0)
    return {"armable": armable, "n": n, "net_median": round(statistics.median(nets), 3),
            "net_moyen": round(sum(nets) / n, 3), "pf": _pf(nets), "dd_bps": _drawdown(nets),
            "median_moitie1": (round(med1, 3) if med1 is not None else None),
            "median_moitie2": (round(med2, 3) if med2 is not None else None),
            "median_sans_meilleur": (round(med_loo, 3) if med_loo is not None else None),
            "motif": ("ARME_MICRO_COHORTE" if armable else "SHADOW_CONTINUE")}


__all__ = ["selectionner_sentinelles", "entree_causale", "execution_bps", "mesurer_episode", "decision",
           "est_causal", "HORIZONS_S", "LATENCE_MS_DEFAUT", "TOUCH_MULT"]

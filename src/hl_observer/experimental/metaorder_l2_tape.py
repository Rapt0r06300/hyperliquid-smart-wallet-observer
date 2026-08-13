"""TAPE L2/OFI SHADOW — SCHÉMA v3 (rectif Flo 25/07) : niveaux BRUTS conservés pour tout recalculer.

Pour CHAQUE fill métaordre, on persiste (append-only, borné, compact) :
  • trois snapshots — PRE (avant le fill), ENTRÉE (1er carnet POSTÉRIEUR au fill), plusieurs POST ;
  • top-5 bid/ask COMPLETS : prix, taille ET **nombre d'ordres** (`n`) — niveaux BRUTS toujours conservés ;
  • horloges séparées : `fill_exchange_time`, `book_exchange_time`, réceptions locales MONOTONES ;
  • `metaorder_id`, `fill_id`, `coin`, `stade` (FIRST_SLICE/CONTINUATION/REVERSAL live ; LATE_STAGE dérivé offline).

On dérive ensuite (mais on GARDE les niveaux bruts pour tout recalculer) : **OFI par niveau**, OFI agrégé, OFI
**normalisé par profondeur**, et `book_imbalance_top5` (statique). `latence_pipeline_ms` = book_recv − fill_recv,
TOUJOURS ≥ 0. **Sans état pré-fill → `OFI_NON_MESURABLE`** (rien inventé). Ne JAMAIS comparer une valeur OFI
BRUTE entre coins différents (échelles ≠) : c'est pourquoi l'OFI normalisé par profondeur est aussi fourni.

Schéma versionné `shadow_l2_v3` ; v1/v2 ignorés dans les stats. Lecture seule (l2Book public), aucune position,
RAW intact. `shadow=true`, `real_execution=false`. 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

TAPE_RELPATH = Path("runtime") / "data" / "metaorder_l2_tape.jsonl"
SCHEMA_VERSION = "shadow_l2_v3"


def cle_fill(coin, fill_id, fill_time) -> tuple:
    return (str(coin).upper() if coin else None, fill_id, int(fill_time or 0))


def metaorder_id(vault, coin, sens, t0) -> str:
    brut = f"{str(vault).lower()}|{str(coin).upper()}|{int(sens)}|{int(t0)}"
    return "mo-" + hashlib.sha1(brut.encode("utf-8")).hexdigest()[:12]


def resume_book(book_brut: dict) -> dict | None:
    """Résumé d'un l2Book BRUT : bid/ask/mid, spread bps, et top-5 [px, sz, **n**] (nombre d'ordres) de chaque
    côté — niveaux BRUTS conservés. `book_exchange_time` = champ `time` HL. None si illisible."""
    try:
        bids, asks = book_brut["levels"][0], book_brut["levels"][1]
        bid, ask = float(bids[0]["px"]), float(asks[0]["px"])
        if bid <= 0 or ask <= 0:
            return None
        mid = 0.5 * (bid + ask)
        top = lambda cote: [[float(x["px"]), float(x["sz"]), int(x.get("n") or 0)] for x in cote[:5]]  # noqa: E731
        return {"bid": bid, "ask": ask, "mid": round(mid, 8), "spread_bps": round((ask - bid) / mid * 1e4, 3),
                "bids5": top(bids), "asks5": top(asks), "book_exchange_time": book_brut.get("time")}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def book_imbalance_top5(resume: dict | None) -> float | None:
    """Déséquilibre STATIQUE (Σ tailles bid − Σ tailles ask, top-5) — une PHOTO, PAS un OFI."""
    try:
        return round(
            sum(level[1] for level in resume["bids5"])
            - sum(level[1] for level in resume["asks5"]),
            4,
        )
    except (KeyError, TypeError, IndexError):
        return None


def profondeur_top5(resume: dict | None) -> float | None:
    """Profondeur totale top-5 (Σ tailles bid + Σ tailles ask) — sert à NORMALISER l'OFI (comparable entre coins)."""
    try:
        return round(
            sum(level[1] for level in resume["bids5"])
            + sum(level[1] for level in resume["asks5"]),
            4,
        )
    except (KeyError, TypeError, IndexError):
        return None


def _contrib_bid(pv, cv, i):
    if i >= len(pv) or i >= len(cv):
        return 0.0
    ppx, psz, cpx, csz = pv[i][0], pv[i][1], cv[i][0], cv[i][1]
    return csz if cpx > ppx else (csz - psz if cpx == ppx else -psz)


def _contrib_ask(pv, cv, i):
    if i >= len(pv) or i >= len(cv):
        return 0.0
    ppx, psz, cpx, csz = pv[i][0], pv[i][1], cv[i][0], cv[i][1]
    return -csz if cpx < ppx else (-(csz - psz) if cpx == ppx else psz)


def ofi_par_niveau(prev: dict | None, cur: dict | None) -> list | None:
    """OFI PAR NIVEAU (liste top-5) entre deux snapshots SUCCESSIFS : contribution bid + ask à CHAQUE niveau
    (>0 = pression acheteuse). None si un snapshot manque (→ OFI_NON_MESURABLE). Recalculable depuis les niveaux."""
    if not prev or not cur:
        return None
    try:
        pb, cb, pa, ca = prev["bids5"], cur["bids5"], prev["asks5"], cur["asks5"]
    except (KeyError, TypeError):
        return None
    return [round(_contrib_bid(pb, cb, i) + _contrib_ask(pa, ca, i), 4) for i in range(5)]


def ofi_top5(prev: dict | None, cur: dict | None) -> float | None:
    """OFI AGRÉGÉ = somme de l'OFI par niveau (top-5). None si non mesurable."""
    niv = ofi_par_niveau(prev, cur)
    return round(sum(niv), 4) if niv is not None else None


def ofi_normalise_profondeur(prev: dict | None, cur: dict | None) -> float | None:
    """OFI NORMALISÉ par la profondeur top-5 du snapshot courant (sans dimension) → COMPARABLE entre coins,
    contrairement à l'OFI brut. None si non mesurable."""
    o, d = ofi_top5(prev, cur), profondeur_top5(cur)
    return round(o / d, 6) if (o is not None and d) else None


def ofi_multi_niveaux(prev: dict | None, cur: dict | None) -> dict | None:
    """OFI L1/L3/L5 et OFI integre, tous issus du meme prefixe de carnets."""
    levels = ofi_par_niveau(prev, cur)
    depth = profondeur_top5(cur)
    if levels is None:
        return None
    integrated = sum(value / (index + 1.0) for index, value in enumerate(levels))
    return {
        "ofi_l1": round(sum(levels[:1]), 6),
        "ofi_l3": round(sum(levels[:3]), 6),
        "ofi_l5": round(sum(levels[:5]), 6),
        "integrated_ofi": round(integrated, 6),
        "integrated_ofi_normalized": round(integrated / depth, 8) if depth else None,
        "depth_normalizer": depth,
    }


def microprice(resume: dict | None) -> float | None:
    """Microprice top-of-book, seulement pour un BBO valide et non croise."""
    try:
        bid = float(resume["bid"])
        ask = float(resume["ask"])
        bid_size = float(resume["bids5"][0][1])
        ask_size = float(resume["asks5"][0][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    total = bid_size + ask_size
    if bid <= 0 or ask <= bid or bid_size < 0 or ask_size < 0 or total <= 0:
        return None
    return round((ask * bid_size + bid * ask_size) / total, 10)


def microprice_deviation_bps(resume: dict | None) -> float | None:
    """Ecart microprice-mid; positif = pression immediate acheteuse."""
    price = microprice(resume)
    try:
        mid = float(resume["mid"])
    except (KeyError, TypeError, ValueError):
        return None
    return round((price - mid) / mid * 10_000.0, 8) if price is not None and mid > 0 else None


def queue_depletion(prev: dict | None, cur: dict | None) -> dict:
    """Depletion top-level; refuse d'attribuer une taille si le niveau de prix a change."""
    result = {
        "bid_depletion_ratio": None,
        "ask_depletion_ratio": None,
        "queue_pressure": None,
        "status": "QUEUE_DEPLETION_UNMEASURABLE",
    }
    try:
        prev_bid, prev_ask = prev["bids5"][0], prev["asks5"][0]
        cur_bid, cur_ask = cur["bids5"][0], cur["asks5"][0]
        if float(prev_bid[0]) != float(cur_bid[0]) or float(prev_ask[0]) != float(cur_ask[0]):
            result["status"] = "PRICE_LEVEL_CHANGED"
            return result
        previous_bid_size = float(prev_bid[1])
        previous_ask_size = float(prev_ask[1])
        bid_depletion = max(0.0, previous_bid_size - float(cur_bid[1])) / previous_bid_size
        ask_depletion = max(0.0, previous_ask_size - float(cur_ask[1])) / previous_ask_size
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return result
    result.update({
        "bid_depletion_ratio": round(bid_depletion, 8),
        "ask_depletion_ratio": round(ask_depletion, 8),
        "queue_pressure": round(ask_depletion - bid_depletion, 8),
        "status": "MEASURED_SAME_PRICE_LEVEL",
    })
    return result


def depth_shape(resume: dict | None) -> dict | None:
    """Pente/convexite top-5, sans pretendre reconstruire la file MBO."""
    try:
        bids = [max(0.0, float(level[1])) for level in resume["bids5"]]
        asks = [max(0.0, float(level[1])) for level in resume["asks5"]]
    except (KeyError, TypeError, ValueError):
        return None
    if not bids or not asks or sum(bids) <= 0 or sum(asks) <= 0:
        return None

    def _side(values):
        near = sum(values[:2])
        far = sum(values[2:])
        total = near + far
        slope = (values[-1] - values[0]) / max(1, len(values) - 1)
        return round(slope, 8), round((far - near) / total, 8)

    bid_slope, bid_convexity = _side(bids)
    ask_slope, ask_convexity = _side(asks)
    return {
        "bid_depth_slope": bid_slope,
        "ask_depth_slope": ask_slope,
        "bid_depth_convexity": bid_convexity,
        "ask_depth_convexity": ask_convexity,
    }


def aggressive_trade_imbalance(trades) -> float | None:
    """Imbalance notionnel des trades publics; inconnu reste non mesurable."""
    signed = 0.0
    total = 0.0
    for trade in trades or []:
        try:
            notional = abs(float(trade.get("sz")) * float(trade.get("px")))
        except (AttributeError, TypeError, ValueError):
            continue
        side = str(trade.get("side") or trade.get("dir") or "").upper()
        if side in {"B", "BUY", "BID"}:
            direction = 1.0
        elif side in {"A", "S", "SELL", "ASK"}:
            direction = -1.0
        else:
            continue
        signed += direction * notional
        total += notional
    return round(signed / total, 8) if total > 0 else None


def add_cancel_imbalance(book_events) -> dict:
    """Imbalance ADD/CANCEL seulement si les evenements sont identifies, jamais deduit d'un snapshot."""
    signed = 0.0
    total = 0.0
    observed = 0
    for event in book_events or []:
        try:
            size = abs(float(event.get("size", event.get("sz"))))
        except (AttributeError, TypeError, ValueError):
            continue
        action = str(event.get("action") or "").upper()
        side = str(event.get("side") or "").upper()
        if action not in {"ADD", "CANCEL"} or side not in {"BID", "ASK"}:
            continue
        direction = 1.0 if (action, side) in {("ADD", "BID"), ("CANCEL", "ASK")} else -1.0
        signed += direction * size
        total += size
        observed += 1
    return {
        "value": round(signed / total, 8) if total > 0 else None,
        "event_count": observed,
        "status": "MEASURED_EVENTS" if observed else "ADD_CANCEL_UNMEASURABLE_FROM_SNAPSHOTS",
    }


def spread_regime(resume: dict | None, *, tight_bps: float = 3.0, wide_bps: float = 15.0) -> str:
    try:
        spread = float(resume["spread_bps"])
    except (KeyError, TypeError, ValueError):
        return "UNMEASURABLE"
    if spread <= tight_bps:
        return "TIGHT"
    if spread >= wide_bps:
        return "WIDE"
    return "NORMAL"


def microstructure_features(
    prev: dict | None,
    cur: dict | None,
    *,
    trades=None,
    book_events=None,
) -> dict:
    """Feature bundle SHADOW causal; aucune feature absente n'est remplacee par zero."""
    multi = ofi_multi_niveaux(prev, cur)
    depletion = queue_depletion(prev, cur)
    add_cancel = add_cancel_imbalance(book_events)
    return {
        **(multi or {
            "ofi_l1": None,
            "ofi_l3": None,
            "ofi_l5": None,
            "integrated_ofi": None,
            "integrated_ofi_normalized": None,
            "depth_normalizer": profondeur_top5(cur),
        }),
        "microprice": microprice(cur),
        "microprice_deviation_bps": microprice_deviation_bps(cur),
        **depletion,
        **(depth_shape(cur) or {
            "bid_depth_slope": None,
            "ask_depth_slope": None,
            "bid_depth_convexity": None,
            "ask_depth_convexity": None,
        }),
        "aggressive_trade_imbalance": aggressive_trade_imbalance(trades),
        "add_cancel_imbalance": add_cancel["value"],
        "add_cancel_status": add_cancel["status"],
        "spread_regime": spread_regime(cur),
        "shadow": True,
        "real_execution": False,
    }


def microstructure_timing_gate(
    prev: dict | None,
    cur: dict | None,
    *,
    sens: int,
    trades=None,
    book_events=None,
    max_spread_bps: float = 15.0,
    max_opposition: float = 0.10,
    max_microprice_opposition_bps: float = 2.0,
) -> dict:
    """Gate SHADOW deny-by-default contre un carnet oppose, large ou non mesurable."""
    features = microstructure_features(prev, cur, trades=trades, book_events=book_events)
    reasons: list[str] = []
    direction = 1 if int(sens or 0) > 0 else (-1 if int(sens or 0) < 0 else 0)
    if direction == 0:
        reasons.append("SIDE_UNMEASURABLE")
    try:
        bid = float(cur["bid"])
        ask = float(cur["ask"])
        spread = float(cur["spread_bps"])
    except (KeyError, TypeError, ValueError):
        bid = ask = spread = None
        reasons.append("BBO_UNMEASURABLE")
    if bid is not None and ask is not None and bid >= ask:
        reasons.append("CROSSED_BOOK")
    if spread is not None and spread > max_spread_bps:
        reasons.append("SPREAD_TOO_WIDE")
    ofi = features["integrated_ofi_normalized"]
    if ofi is None:
        reasons.append("OFI_UNMEASURABLE")
    elif direction * ofi < -abs(max_opposition):
        reasons.append("OFI_OPPOSED")
    micro_deviation = features["microprice_deviation_bps"]
    if (
        micro_deviation is not None
        and direction * micro_deviation < -abs(max_microprice_opposition_bps)
    ):
        reasons.append("MICROPRICE_OPPOSED")
    aggressive = features["aggressive_trade_imbalance"]
    if aggressive is not None and direction * aggressive < -abs(max_opposition):
        reasons.append("AGGRESSIVE_FLOW_OPPOSED")
    return {
        "decision": "ALLOW_SHADOW" if not reasons else "ABSTAIN_SHADOW",
        "reasons": sorted(set(reasons)),
        "features": features,
        "shadow": True,
        "real_execution": False,
    }


def ablation_microstructure(rows: list, *, min_observations: int = 30) -> dict:
    """Compare le signal de base au sous-ensemble ALLOW sans promouvoir le gate."""
    base = [
        float(row["pnl_net_bps"])
        for row in rows or []
        if row.get("pnl_net_bps") is not None
    ]
    allowed = [
        float(row["pnl_net_bps"])
        for row in rows or []
        if row.get("pnl_net_bps") is not None
        and (row.get("microstructure_gate") or {}).get("decision") == "ALLOW_SHADOW"
    ]
    base_mean = sum(base) / len(base) if base else None
    allowed_mean = sum(allowed) / len(allowed) if allowed else None
    delta = allowed_mean - base_mean if base_mean is not None and allowed_mean is not None else None
    return {
        "base_n": len(base),
        "allowed_n": len(allowed),
        "base_mean_net_bps": round(base_mean, 8) if base_mean is not None else None,
        "allowed_mean_net_bps": round(allowed_mean, 8) if allowed_mean is not None else None,
        "delta_mean_net_bps": round(delta, 8) if delta is not None else None,
        "promotion_eligible": bool(
            len(base) >= min_observations
            and len(allowed) >= min_observations
            and delta is not None
            and delta > 0
            and allowed_mean is not None
            and allowed_mean > 0
        ),
        "status": "SHADOW_ABLATION_ONLY",
        "real_execution": False,
    }


def latence_pipeline_ms(fill_recv_mono, book_recv_mono) -> float | None:
    """Latence pipeline LOCALE = book_recv_mono − fill_recv_mono (MONOTONE, même process). TOUJOURS ≥ 0 :
    None si le carnet est ANTÉRIEUR au fill (pas un snapshot d'entrée valide)."""
    try:
        d = float(book_recv_mono) - float(fill_recv_mono)
        return round(d, 1) if d >= 0 else None
    except (TypeError, ValueError):
        return None


LATENCE_PLAFOND_ELIGIBLE_MS = 2000.0       # plafond PRÉ-ENREGISTRÉ : au-delà, le carnet d'entrée n'est pas synchronisé


def est_eligible(ligne: dict, *, plafond_ms: float = LATENCE_PLAFOND_ELIGIBLE_MS) -> bool:
    """ÉLIGIBILITÉ STATISTIQUE (≠ simple capture) d'une ligne 'fill' pour les coûts EXÉCUTABLES / l'OOS :
    carnet d'ENTRÉE POSTÉRIEUR au fill en horloge HL (`book_exchange_time ≥ fill_exchange_time`) ET latence
    pipeline ≥ 0 et ≤ plafond pré-enregistré. Sinon **L2_NON_SYNCHRONISE** : la ligne est CONSERVÉE (brute) mais
    EXCLUE des statistiques. Les FIRST_SLICE (abonnement froid) sont souvent au-dessus du plafond → non éligibles."""
    bx, fx, lat = ligne.get("book_exchange_time"), ligne.get("fill_exchange_time"), ligne.get("latence_pipeline_ms")
    try:
        return (bx is not None and fx is not None and lat is not None
                and float(bx) >= float(fx) and 0.0 <= float(lat) <= float(plafond_ms))
    except (TypeError, ValueError):
        return False


def statut_eligibilite(ligne: dict, *, plafond_ms: float = LATENCE_PLAFOND_ELIGIBLE_MS) -> str:
    """'ELIGIBLE' (synchro L2 prouvée) ou 'L2_NON_SYNCHRONISE' (capturé mais hors stats)."""
    return "ELIGIBLE" if est_eligible(ligne, plafond_ms=plafond_ms) else "L2_NON_SYNCHRONISE"


def etat_pre(buffer: list, fill_recv_mono: float) -> dict | None:
    pre = [e for e in buffer if float(e["recv_mono"]) < float(fill_recv_mono)]
    return pre[-1] if pre else None


def etat_entree(buffer: list, fill_recv_mono: float, fill_exchange_time) -> dict | None:
    fx = fill_exchange_time
    for e in buffer:
        if float(e["recv_mono"]) >= float(fill_recv_mono):
            bx = (e.get("resume") or {}).get("book_exchange_time")
            if fx is None or bx is None or float(bx) >= float(fx):
                return e
    return None


def etats_post(buffer: list, entree_recv_mono: float, *, n: int = 3, fenetre_ms: float = 30_000.0) -> list:
    return [e for e in buffer
            if float(entree_recv_mono) < float(e["recv_mono"]) <= float(entree_recv_mono) + fenetre_ms][:n]


def stade_live(etat: dict, fill: dict, *, intervalle_ms: float = 60_000.0) -> tuple:
    """Assigne LIVE (metaorder_id, stade) à un fill via `etat` par (vault, coin) : CONTINUATION si même sens et
    écart ≤ intervalle ; sinon nouveau métaordre → FIRST_SLICE (ou REVERSAL s'il inverse le précédent). LATE_STAGE
    se dérive OFFLINE (join sur metaorder_id). Mute `etat`."""
    vault = str(fill.get("vault") or "")
    coin = str(fill.get("coin") or "").upper()
    sens = int(fill.get("signe") or fill.get("sens") or 0)
    ft = int(fill.get("ts_ms") or fill.get("fill_time") or 0)
    key = (vault, coin)
    st = etat.get(key)
    if st and st["sens"] == sens and (ft - st["last_ft"]) <= intervalle_ms:
        st["last_ft"] = ft
        return st["mo_id"], "CONTINUATION"
    reversal = bool(st and st["sens"] == -sens and (ft - st["last_ft"]) <= intervalle_ms)
    mo = metaorder_id(vault, coin, sens, ft)
    etat[key] = {"sens": sens, "mo_id": mo, "last_ft": ft}
    return mo, ("REVERSAL" if reversal else "FIRST_SLICE")


def _snap(e: dict | None) -> dict | None:
    """Snapshot COMPACT d'un état : réception monotone + temps HL + niveaux BRUTS top-5 [px, sz, n]."""
    if not e:
        return None
    r = e.get("resume") or {}
    return {"recv_mono": round(float(e["recv_mono"]), 1), "recv_wall_ms": e.get("recv_wall_ms"),
            "book_exchange_time": r.get("book_exchange_time"),
            "bids": r.get("bids5"), "asks": r.get("asks5")}


def ligne_fill(fill: dict, *, metaorder_id: str, stade: str, pre: dict | None, entree: dict | None,
               posts: list, fill_recv_mono: float, trades=None, book_events=None) -> dict | None:
    """Ligne v3 d'un fill : PRE/ENTRÉE/POST bruts (px,sz,n) + horloges séparées + features DÉRIVÉES (OFI par
    niveau, agrégé, normalisé profondeur, imbalance) — les niveaux bruts restent pour TOUT recalculer. None si
    aucun état d'entrée postérieur au fill."""
    if entree is None:
        return None
    re_ = entree.get("resume") or {}
    rp = (pre or {}).get("resume")
    coin = str(fill.get("coin") or "").upper()
    fx = int(fill.get("ts_ms") or fill.get("fill_time") or 0)
    features = microstructure_features(rp, re_, trades=trades, book_events=book_events)
    gate = microstructure_timing_gate(
        rp,
        re_,
        sens=int(fill.get("signe") or fill.get("sens") or 0),
        trades=trades,
        book_events=book_events,
    )
    return {"schema_version": SCHEMA_VERSION, "phase": "fill", "coin": coin, "metaorder_id": metaorder_id,
            "fill_id": fill.get("hash"), "stade": stade,
            "sens": int(fill.get("signe") or fill.get("sens") or 0), "vault": str(fill.get("vault") or "")[:42],
            "fill_exchange_time": fx, "book_exchange_time": re_.get("book_exchange_time"),
            "fill_received_at_ms": fill.get("received_at_ms"),
            "book_received_at_ms": entree.get("recv_wall_ms"),
            "fill_recv_mono": round(float(fill_recv_mono), 1), "book_recv_mono": round(float(entree["recv_mono"]), 1),
            "latence_pipeline_ms": latence_pipeline_ms(fill_recv_mono, entree["recv_mono"]),
            "pre": _snap(pre), "entree": _snap(entree), "posts": [_snap(p) for p in posts],   # NIVEAUX BRUTS
            "ofi_par_niveau": ofi_par_niveau(rp, re_), "ofi_top5": ofi_top5(rp, re_),
            "ofi_normalise_profondeur": ofi_normalise_profondeur(rp, re_),
            "book_imbalance_top5": book_imbalance_top5(re_), "profondeur_top5": profondeur_top5(re_),
            "ofi_statut": "OK" if rp else "OFI_NON_MESURABLE", "ofi_mesurable": rp is not None,
            "microstructure_features": features, "microstructure_gate": gate,
            "shadow": True, "real_execution": False}


def ligne_sortie(fill: dict, *, sortie: dict, capture_recv_mono: float, horizon_ms: float,
                 fill_recv_mono: float) -> dict:
    """Ligne de SORTIE v3 : niveaux BRUTS du carnet à ≈ entrée+horizon + **retard RÉEL** vs (fill_recv+horizon)."""
    r = sortie.get("resume") or {}
    cible = float(fill_recv_mono) + float(horizon_ms)
    return {"schema_version": SCHEMA_VERSION, "phase": "sortie", "coin": str(fill.get("coin") or "").upper(),
            "fill_id": fill.get("hash"), "fill_exchange_time": int(fill.get("ts_ms") or 0),
            "book_exchange_time": r.get("book_exchange_time"),
            "fill_received_at_ms": fill.get("received_at_ms"),
            "book_received_at_ms": sortie.get("recv_wall_ms"),
            "retard_sortie_ms": round(float(capture_recv_mono) - cible, 1),
            "bids": r.get("bids5"), "asks": r.get("asks5"), "book_imbalance_top5": book_imbalance_top5(r),
            "shadow": True, "real_execution": False}


def ecrire_lignes(root, lignes: list) -> None:
    if not lignes:
        return
    p = Path(root) / TAPE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for line in lignes:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def charger_tape(root) -> dict:
    """Charge la tape v3 → {cle_fill: {'fill': ligne, 'sortie': ligne}}. Ignore v1/v2 (features douteuses)."""
    p = Path(root) / TAPE_RELPATH
    out: dict = {}
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out
    for line in lignes:
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("schema_version") != SCHEMA_VERSION:
            continue
        k = cle_fill(d.get("coin"), d.get("fill_id"), d.get("fill_exchange_time"))
        out.setdefault(k, {})[d.get("phase")] = d
    return out


__all__ = ["TAPE_RELPATH", "SCHEMA_VERSION", "LATENCE_PLAFOND_ELIGIBLE_MS", "cle_fill", "metaorder_id",
           "resume_book", "book_imbalance_top5", "profondeur_top5", "ofi_par_niveau", "ofi_top5",
           "ofi_normalise_profondeur", "ofi_multi_niveaux", "microprice", "microprice_deviation_bps",
           "queue_depletion", "depth_shape", "aggressive_trade_imbalance", "add_cancel_imbalance",
           "spread_regime", "microstructure_features", "microstructure_timing_gate",
           "ablation_microstructure", "latence_pipeline_ms", "est_eligible", "statut_eligibilite",
           "etat_pre", "etat_entree", "etats_post", "stade_live", "ligne_fill", "ligne_sortie",
           "ecrire_lignes", "charger_tape"]

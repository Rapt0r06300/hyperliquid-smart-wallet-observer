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
    brut = "%s|%s|%d|%d" % (str(vault).lower(), str(coin).upper(), int(sens), int(t0))
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
        return round(sum(l[1] for l in resume["bids5"]) - sum(l[1] for l in resume["asks5"]), 4)
    except (KeyError, TypeError, IndexError):
        return None


def profondeur_top5(resume: dict | None) -> float | None:
    """Profondeur totale top-5 (Σ tailles bid + Σ tailles ask) — sert à NORMALISER l'OFI (comparable entre coins)."""
    try:
        return round(sum(l[1] for l in resume["bids5"]) + sum(l[1] for l in resume["asks5"]), 4)
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
    return {"recv_mono": round(float(e["recv_mono"]), 1), "book_exchange_time": r.get("book_exchange_time"),
            "bids": r.get("bids5"), "asks": r.get("asks5")}


def ligne_fill(fill: dict, *, metaorder_id: str, stade: str, pre: dict | None, entree: dict | None,
               posts: list, fill_recv_mono: float) -> dict | None:
    """Ligne v3 d'un fill : PRE/ENTRÉE/POST bruts (px,sz,n) + horloges séparées + features DÉRIVÉES (OFI par
    niveau, agrégé, normalisé profondeur, imbalance) — les niveaux bruts restent pour TOUT recalculer. None si
    aucun état d'entrée postérieur au fill."""
    if entree is None:
        return None
    re_ = entree.get("resume") or {}
    rp = (pre or {}).get("resume")
    coin = str(fill.get("coin") or "").upper()
    fx = int(fill.get("ts_ms") or fill.get("fill_time") or 0)
    return {"schema_version": SCHEMA_VERSION, "phase": "fill", "coin": coin, "metaorder_id": metaorder_id,
            "fill_id": fill.get("hash"), "stade": stade,
            "sens": int(fill.get("signe") or fill.get("sens") or 0), "vault": str(fill.get("vault") or "")[:42],
            "fill_exchange_time": fx, "book_exchange_time": re_.get("book_exchange_time"),
            "fill_recv_mono": round(float(fill_recv_mono), 1), "book_recv_mono": round(float(entree["recv_mono"]), 1),
            "latence_pipeline_ms": latence_pipeline_ms(fill_recv_mono, entree["recv_mono"]),
            "pre": _snap(pre), "entree": _snap(entree), "posts": [_snap(p) for p in posts],   # NIVEAUX BRUTS
            "ofi_par_niveau": ofi_par_niveau(rp, re_), "ofi_top5": ofi_top5(rp, re_),
            "ofi_normalise_profondeur": ofi_normalise_profondeur(rp, re_),
            "book_imbalance_top5": book_imbalance_top5(re_), "profondeur_top5": profondeur_top5(re_),
            "ofi_statut": "OK" if rp else "OFI_NON_MESURABLE", "ofi_mesurable": rp is not None,
            "shadow": True, "real_execution": False}


def ligne_sortie(fill: dict, *, sortie: dict, capture_recv_mono: float, horizon_ms: float,
                 fill_recv_mono: float) -> dict:
    """Ligne de SORTIE v3 : niveaux BRUTS du carnet à ≈ entrée+horizon + **retard RÉEL** vs (fill_recv+horizon)."""
    r = sortie.get("resume") or {}
    cible = float(fill_recv_mono) + float(horizon_ms)
    return {"schema_version": SCHEMA_VERSION, "phase": "sortie", "coin": str(fill.get("coin") or "").upper(),
            "fill_id": fill.get("hash"), "fill_exchange_time": int(fill.get("ts_ms") or 0),
            "book_exchange_time": r.get("book_exchange_time"),
            "retard_sortie_ms": round(float(capture_recv_mono) - cible, 1),
            "bids": r.get("bids5"), "asks": r.get("asks5"), "book_imbalance_top5": book_imbalance_top5(r),
            "shadow": True, "real_execution": False}


def ecrire_lignes(root, lignes: list) -> None:
    if not lignes:
        return
    p = Path(root) / TAPE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for l in lignes:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")


def charger_tape(root) -> dict:
    """Charge la tape v3 → {cle_fill: {'fill': ligne, 'sortie': ligne}}. Ignore v1/v2 (features douteuses)."""
    p = Path(root) / TAPE_RELPATH
    out: dict = {}
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out
    for l in lignes:
        if not l.strip():
            continue
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if d.get("schema_version") != SCHEMA_VERSION:
            continue
        k = cle_fill(d.get("coin"), d.get("fill_id"), d.get("fill_exchange_time"))
        out.setdefault(k, {})[d.get("phase")] = d
    return out


__all__ = ["TAPE_RELPATH", "SCHEMA_VERSION", "LATENCE_PLAFOND_ELIGIBLE_MS", "cle_fill", "metaorder_id",
           "resume_book", "book_imbalance_top5", "profondeur_top5", "ofi_par_niveau", "ofi_top5",
           "ofi_normalise_profondeur", "latence_pipeline_ms", "est_eligible", "statut_eligibilite",
           "etat_pre", "etat_entree", "etats_post", "stade_live", "ligne_fill", "ligne_sortie",
           "ecrire_lignes", "charger_tape"]

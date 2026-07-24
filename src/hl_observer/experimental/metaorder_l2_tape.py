"""TAPE L2/OFI SHADOW synchronisée autour des fills métaordre — SCHÉMA v2 (rectif Flo 24/07).

Corrige les mauvaises features de la v1 AVANT accumulation :
  • `book_imbalance_top5` (STATIQUE, un seul snapshot : Σbid5 − Σask5) N'EST PAS un OFI ;
  • le **vrai OFI top-5** se calcule sur les VARIATIONS entre snapshots L2 SUCCESSIFS (Cont et al.) — donc il
    faut un BUFFER de carnets horodatés. On abonne le coin au l2Book **dès le 1er fill (FIRST_SLICE)** et on
    garde un petit buffer WS. Par continuation : un état PRÉ-fill + plusieurs POST-fill. **Sans état pré-fill →
    `OFI_NON_MESURABLE`** (rien inventé).

QUATRE horloges STRICTEMENT séparées (une latence de −650 ms n'est pas une latence, c'est un mélange) :
  • `fill_exchange_time`  : temps HL du fill ;
  • `book_exchange_time`  : temps HL du carnet (champ `time` du l2Book) ;
  • `fill_recv_mono` / `book_recv_mono` : réception LOCALE MONOTONE (même process → comparables) ;
  • `latence_pipeline_ms` = book_recv_mono − fill_recv_mono, **TOUJOURS ≥ 0** (snapshot d'entrée POSTÉRIEUR au
    fill exigé). Le snapshot de SORTIE journalise son retard réel vs +horizon.

Lecture seule (l2Book public), `shadow=true`, `real_execution=false`. Aucune position, RAW intact.
"""
from __future__ import annotations

import json
from pathlib import Path

TAPE_RELPATH = Path("runtime") / "data" / "metaorder_l2_tape.jsonl"
SCHEMA_VERSION = "shadow_l2_v2"


def cle_fill(coin, hsh, fill_time) -> tuple:
    return (str(coin).upper() if coin else None, hsh, int(fill_time or 0))


def resume_book(book_brut: dict) -> dict | None:
    """Résumé d'un l2Book BRUT : bid/ask/mid, spread bps, 5 niveaux [px,sz] de chaque côté, et
    `book_exchange_time` (champ `time` HL du carnet). None si illisible."""
    try:
        bids, asks = book_brut["levels"][0], book_brut["levels"][1]
        bid, ask = float(bids[0]["px"]), float(asks[0]["px"])
        if bid <= 0 or ask <= 0:
            return None
        mid = 0.5 * (bid + ask)
        top = lambda cote: [[float(x["px"]), float(x["sz"])] for x in cote[:5]]   # noqa: E731
        b5, a5 = top(bids), top(asks)
        return {"bid": bid, "ask": ask, "mid": round(mid, 8), "spread_bps": round((ask - bid) / mid * 1e4, 3),
                "bids5": b5, "asks5": a5, "book_exchange_time": book_brut.get("time"),
                "book_imbalance_top5": round(sum(s for _, s in b5) - sum(s for _, s in a5), 4)}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def book_imbalance_top5(resume: dict | None) -> float | None:
    """Déséquilibre STATIQUE du carnet (Σ tailles bid − Σ tailles ask, top-5) — une PHOTO, PAS un OFI."""
    if not resume:
        return None
    try:
        return round(sum(s for _, s in resume["bids5"]) - sum(s for _, s in resume["asks5"]), 4)
    except (KeyError, TypeError, ValueError):
        return None


def ofi_top5(prev: dict | None, cur: dict | None) -> float | None:
    """VRAI OFI top-5 entre deux snapshots SUCCESSIFS (Cont, Kukanov & Stoikov). Contributions déjà SIGNÉES,
    OFI = Σ_bid + Σ_ask (>0 = pression acheteuse nette) :
    BID (demande) → px↑ : +sz_cur ; px= : +(sz_cur−sz_prev) ; px↓ : −sz_prev.
    ASK (offre)   → px↓ : −sz_cur (offre plus agressive = vente) ; px= : −(sz_cur−sz_prev) (offre ajoutée =
                    vente ; retirée = +) ; px↑ : +sz_prev (offre retirée = moins de vente).
    **None si un snapshot manque** (→ OFI_NON_MESURABLE)."""
    if not prev or not cur:
        return None
    try:
        pb, cb, pa, ca = prev["bids5"], cur["bids5"], prev["asks5"], cur["asks5"]
    except (KeyError, TypeError):
        return None
    e_bid = 0.0
    for i in range(min(len(pb), len(cb), 5)):
        (ppx, psz), (cpx, csz) = pb[i], cb[i]
        e_bid += csz if cpx > ppx else (csz - psz if cpx == ppx else -psz)
    e_ask = 0.0
    for i in range(min(len(pa), len(ca), 5)):
        (ppx, psz), (cpx, csz) = pa[i], ca[i]
        e_ask += -csz if cpx < ppx else (-(csz - psz) if cpx == ppx else psz)
    return round(e_bid + e_ask, 4)


def latence_pipeline_ms(fill_recv_mono, book_recv_mono) -> float | None:
    """Latence de NOTRE pipeline = réception locale du carnet − réception locale du fill (MONOTONE, même
    process). TOUJOURS ≥ 0 : None si le carnet est ANTÉRIEUR au fill (pas un snapshot d'entrée valide)."""
    try:
        d = float(book_recv_mono) - float(fill_recv_mono)
        return round(d, 1) if d >= 0 else None
    except (TypeError, ValueError):
        return None


def etat_pre(buffer: list, fill_recv_mono: float) -> dict | None:
    """Dernier état du buffer STRICTEMENT ANTÉRIEUR à la réception du fill (base de l'OFI). None si aucun
    (ex. FIRST_SLICE : rien avant → OFI_NON_MESURABLE)."""
    pre = [e for e in buffer if float(e["recv_mono"]) < float(fill_recv_mono)]
    return pre[-1] if pre else None


def etat_entree(buffer: list, fill_recv_mono: float, fill_exchange_time) -> dict | None:
    """Premier état POSTÉRIEUR au fill (réception locale ≥ fill ET, si dispo, temps HL du carnet ≥ temps HL du
    fill). C'est le carnet contre lequel on EXÉCUTERAIT — obligatoirement après le fill. None si pas encore là."""
    fx = fill_exchange_time
    for e in buffer:
        if float(e["recv_mono"]) >= float(fill_recv_mono):
            bx = (e.get("resume") or {}).get("book_exchange_time")
            if fx is None or bx is None or float(bx) >= float(fx):
                return e
    return None


def etats_post(buffer: list, entree_recv_mono: float, *, n: int = 3, fenetre_ms: float = 30_000.0) -> list:
    """Jusqu'à `n` états postérieurs à l'entrée, dans `fenetre_ms` (évolution de l'OFI après le fill)."""
    return [e for e in buffer
            if float(entree_recv_mono) < float(e["recv_mono"]) <= float(entree_recv_mono) + fenetre_ms][:n]


def ligne_continuation(fill: dict, *, pre: dict | None, entree: dict | None, posts: list,
                       fill_recv_mono: float) -> dict | None:
    """Ligne de tape v2 pour un fill : 4 horloges séparées, latence pipeline ≥ 0, `book_imbalance_top5`
    (statique) SÉPARÉ du **vrai OFI** (pré→entrée), OFI post successifs, `OFI_NON_MESURABLE` si pas de pré.
    None si aucun état d'entrée postérieur (snapshot d'entrée pas encore disponible)."""
    if entree is None:
        return None
    r = entree.get("resume") or {}
    coin = str(fill.get("coin") or "").upper()
    fx = int(fill.get("ts_ms") or fill.get("fill_time") or 0)
    ofi = ofi_top5((pre or {}).get("resume"), r) if pre else None
    # OFI successifs post-fill (entrée→post1→post2…)
    seq, prev_r = [], r
    for e in posts:
        seq.append(ofi_top5(prev_r, e.get("resume")))
        prev_r = e.get("resume") or prev_r
    return {"schema_version": SCHEMA_VERSION, "phase": "continuation", "coin": coin,
            "sens": int(fill.get("signe") or fill.get("sens") or 0), "vault": str(fill.get("vault") or "")[:42],
            "hash": fill.get("hash"),
            "fill_exchange_time": fx, "book_exchange_time": r.get("book_exchange_time"),
            "fill_recv_mono": round(float(fill_recv_mono), 1), "book_recv_mono": round(float(entree["recv_mono"]), 1),
            "latence_pipeline_ms": latence_pipeline_ms(fill_recv_mono, entree["recv_mono"]),
            "mid": r.get("mid"), "spread_bps": r.get("spread_bps"),
            "top5": {"bids": r.get("bids5"), "asks": r.get("asks5")},
            "book_imbalance_top5": r.get("book_imbalance_top5"),           # STATIQUE (photo)
            "ofi_top5": ofi, "ofi_mesurable": pre is not None,            # VRAI OFI (variation) ; sinon…
            "ofi_statut": "OK" if pre is not None else "OFI_NON_MESURABLE",
            "ofi_post_sequence": seq, "n_post": len(posts),
            "shadow": True, "real_execution": False}


def ligne_sortie(fill: dict, *, entree_resume: dict, capture_recv_mono: float, horizon_ms: float,
                 fill_recv_mono: float) -> dict:
    """Ligne de SORTIE : carnet à ≈ entrée+horizon + **retard RÉEL** du snapshot vs la cible (fill_recv+horizon)."""
    cible = float(fill_recv_mono) + float(horizon_ms)
    return {"schema_version": SCHEMA_VERSION, "phase": "sortie", "coin": str(fill.get("coin") or "").upper(),
            "hash": fill.get("hash"), "fill_exchange_time": int(fill.get("ts_ms") or 0),
            "book_exchange_time": entree_resume.get("book_exchange_time"),
            "retard_sortie_ms": round(float(capture_recv_mono) - cible, 1),   # >0 = snapshot APRÈS +horizon
            "mid": entree_resume.get("mid"), "spread_bps": entree_resume.get("spread_bps"),
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
    """Charge la tape → {cle_fill: {'continuation': ligne, 'sortie': ligne}} (schéma v2). Lecture seule."""
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
            continue                                             # on ignore l'ancien schéma (features douteuses)
        k = cle_fill(d.get("coin"), d.get("hash"), d.get("fill_exchange_time"))
        out.setdefault(k, {})[d.get("phase")] = d
    return out


__all__ = ["TAPE_RELPATH", "SCHEMA_VERSION", "cle_fill", "resume_book", "book_imbalance_top5", "ofi_top5",
           "latence_pipeline_ms", "etat_pre", "etat_entree", "etats_post", "ligne_continuation", "ligne_sortie",
           "ecrire_lignes", "charger_tape"]

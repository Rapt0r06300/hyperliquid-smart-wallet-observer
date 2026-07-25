"""LOT 6 — EXÉCUTION HONNÊTE (Flo 25/07). Cœur PUR, testable sans réseau.

Trois honnêtetés dures :
  1. TAKER = VWAP RÉEL selon la profondeur disponible. Profondeur < notional -> NON_MESURABLE (jamais un
     prix moyen optimiste tiré du top-of-book).
  2. MAKER = simulation de file CONSERVATRICE (RiskAverseQueueModel) : on suppose être en QUEUE ARRIÈRE ;
     rempli SEULEMENT si le volume qui traverse notre prix >= file devant + notre taille. Sinon NON_REMPLI.
  3. MARKOUTS SÉPARÉS à 1/3/5/15/30/60 s (et min) — INTERDIT de cacher une tolérance de sortie à 60 s.
     Le LAG RÉEL de chaque entrée et de chaque sortie est rendu explicitement.

0 ordre, 0 clé. Rien ici ne dépend d'un réseau.
"""
from __future__ import annotations

from bisect import bisect_right

HORIZONS_S = (1, 3, 5, 15, 30, 60, 300, 900, 1800, 3600)
LATENCE_MS = 400.0
FRAICHEUR_MAX_MS = 2000.0        # au-delà, la cotation à l'instant visé est absente -> NON_MESURABLE (honnête)
FEE_AR_BPS = 9.0
SLIPPAGE_BPS = 1.0


# ─────────────── TAKER : VWAP selon profondeur ───────────────
def vwap_taker(niveaux, notional_usd: float) -> dict:
    """VWAP en CONSOMMANT la profondeur (niveaux = [(px, taille_usd)] du meilleur au pire, du côté payé).
    Profondeur totale < notional -> NON_MESURABLE (on ne remplit pas ce qu'on ne voit pas)."""
    if not niveaux:
        return {"statut": "NON_MESURABLE", "motif": "AUCUNE_PROFONDEUR"}
    reste = notional_usd
    cout = 0.0
    for px, sz in niveaux:
        if px <= 0 or sz <= 0:
            continue
        pris = min(reste, sz)
        cout += pris * px
        reste -= pris
        if reste <= 1e-9:
            return {"statut": "OK", "vwap": cout / notional_usd, "profondeur_ok": True}
    return {"statut": "NON_MESURABLE", "motif": "PROFONDEUR_INSUFFISANTE",
            "manque_usd": round(reste, 2), "profondeur_dispo_usd": round(notional_usd - reste, 2)}


# ─────────────── MAKER : RiskAverseQueueModel ───────────────
def queue_model_maker(*, file_devant_usd: float, taille_usd: float, volume_traverse_usd: float) -> dict:
    """CONSERVATEUR : on suppose être DERRIÈRE toute la file. Rempli SEULEMENT si le volume agressif qui
    traverse notre prix pendant l'attente >= file devant + notre taille. Aucun remplissage partiel optimiste."""
    requis = file_devant_usd + taille_usd
    if volume_traverse_usd >= requis:
        return {"statut": "REMPLI", "requis_usd": round(requis, 2)}
    return {"statut": "NON_REMPLI", "requis_usd": round(requis, 2),
            "manque_usd": round(requis - volume_traverse_usd, 2)}


# ─────────────── MARKOUTS causaux séparés + lag réel ───────────────
def _quote_apres(prix, cible_ms, *, fraicheur_ms):
    """1re cotation (ts,bid,ask) STRICTEMENT après cible_ms, dans la fenêtre de fraîcheur. None sinon."""
    temps = [p[0] for p in prix]
    i = bisect_right(temps, cible_ms)
    if i >= len(prix) or prix[i][0] - cible_ms > fraicheur_ms:
        return None
    return prix[i]


def markouts_causaux(signal: dict, prix, *, horizons_s=HORIZONS_S, latence_ms=LATENCE_MS,
                     fraicheur_ms=FRAICHEUR_MAX_MS, fee_ar_bps=FEE_AR_BPS, slippage_bps=SLIPPAGE_BPS) -> dict:
    """Entrée = 1re cotation après ts_signal+latence (lag RÉEL rendu). Pour CHAQUE horizon SÉPARÉMENT :
    sortie = 1re cotation après entrée+h (lag réel rendu), net au bid/ask. sens+1 long (achat ask/vente bid).
    Aucune tolérance de sortie cachée : chaque horizon a son propre net et son propre lag."""
    prix = sorted(prix, key=lambda p: p[0])
    seuil = signal["ts_ms"] + latence_ms
    e = _quote_apres(prix, seuil, fraicheur_ms=fraicheur_ms)
    if e is None:
        return {"statut": "NON_MESURABLE", "motif": "PAS_D_ENTREE_CAUSALE", "coin": signal.get("coin")}
    te, be, ae = e
    entree_lag_ms = round(te - seuil, 1)
    sens = signal["sens"]
    par_h = {}
    for h in horizons_s:
        s = _quote_apres(prix, te + h * 1000, fraicheur_ms=fraicheur_ms)
        if s is None:
            par_h[str(h)] = {"statut": "NON_MESURABLE"}
            continue
        ts2, bs, as_ = s
        if sens > 0:
            brut = (bs - ae) / ae * 1e4
        else:
            brut = (be - as_) / be * 1e4
        par_h[str(h)] = {"statut": "OK", "net_bps": round(brut - fee_ar_bps - slippage_bps, 4),
                         "brut_bps": round(brut, 4), "sortie_lag_ms": round(ts2 - (te + h * 1000), 1)}
    return {"statut": "OK", "coin": signal.get("coin"), "sens": sens, "ts_signal_ms": signal["ts_ms"],
            "entree_ts_ms": te, "entree_lag_ms": entree_lag_ms, "latence_ms": latence_ms, "par_horizon": par_h}


__all__ = ["vwap_taker", "queue_model_maker", "markouts_causaux", "HORIZONS_S", "LATENCE_MS", "FEE_AR_BPS"]

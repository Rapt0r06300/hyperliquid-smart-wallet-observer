"""MARKET MAKING, LADDER, ORDER FLOW (IDEA-56 → 60).

Famille PASSIVE_LADDER en PAPER uniquement, et les mesures d'order flow qui décident si un signal mérite
d'être suivi :

  • IDEA-56 : ladder passive multi-niveaux (spread, microprice, OFI, imbalance, vol, inventaire) ;
  • IDEA-57 : risque d'inventaire — inventaire ouvert, perte latente, concentration, distance de
    liquidation THÉORIQUE (paper : aucune liquidation réelle n'existe) ;
  • IDEA-58 : OFI multi-niveaux (pas seulement le top of book) avec vitesse et ajouts/annulations ;
  • IDEA-59 : queue depletion comme CONFIRMATION d'un signal, jamais comme signal isolé ;
  • IDEA-60 : flow toxicity CAUSAL — état initial = dernier mid connu <= t, markout = premier mid >=
    t+horizon. Le « nearest timestamp » symétrique est interdit : il laisse fuiter le futur.

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ─────────────────────── IDEA-58 : OFI multi-niveaux ───────────────────────
def ofi_multi_niveaux(bids_avant, asks_avant, bids_apres, asks_apres, *, n_niveaux: int = 5) -> dict:
    """IDEA-58 — Order Flow Imbalance sur N niveaux : variation de la taille au bid moins celle à l'ask.
    Positif = pression acheteuse. On rend AUSSI le détail par niveau : un OFI porté par le seul top of
    book est beaucoup plus fragile qu'un OFI diffusé sur la profondeur."""
    def _tailles(niveaux):
        out = []
        for niv in (niveaux or [])[:n_niveaux]:
            if isinstance(niv, dict):
                out.append((_f(niv.get("px")), _f(niv.get("sz"))))
            else:
                p = list(niv) + [None, None]
                out.append((_f(p[0]), _f(p[1])))
        return out
    ba, aa = _tailles(bids_avant), _tailles(asks_avant)
    bp, ap = _tailles(bids_apres), _tailles(asks_apres)
    par_niveau, ofi = [], 0.0
    for i in range(min(len(ba), len(bp), len(aa), len(ap))):
        d_bid = (bp[i][1] or 0.0) - (ba[i][1] or 0.0)
        d_ask = (ap[i][1] or 0.0) - (aa[i][1] or 0.0)
        v = d_bid - d_ask
        par_niveau.append({"niveau": i, "delta_bid": d_bid, "delta_ask": d_ask, "ofi": round(v, 6)})
        ofi += v
    top = par_niveau[0]["ofi"] if par_niveau else 0.0
    concentre = (abs(top) >= 0.8 * abs(ofi)) if ofi else None
    return {"ofi_total": round(ofi, 6), "ofi_top": round(top, 6), "par_niveau": par_niveau,
            "n_niveaux": len(par_niveau),
            "concentre_sur_le_top": concentre,
            "avertissement": ("OFI porte par le seul top of book — signal fragile" if concentre else None)}


def microprice(bid: float, ask: float, bid_sz: float, ask_sz: float):
    """Prix pondéré par les tailles : plus proche du côté le plus lourd. None si carnet invalide."""
    b, a, bs, asz = _f(bid), _f(ask), _f(bid_sz), _f(ask_sz)
    if None in (b, a, bs, asz) or a <= b or (bs + asz) <= 0:
        return None
    return round((b * asz + a * bs) / (bs + asz), 8)


# ─────────────────────── IDEA-59 : queue depletion comme confirmation ───────────────────────
def confirmation_depletion(*, signal_direction: int, depletion_rate=None, volume_traversant=None,
                           profondeur_perdue=None, cancels_nets=None, seuil_depletion: float = 0.5) -> dict:
    """IDEA-59 — le depletion CONFIRME un signal, il ne le crée pas. Sans signal directionnel en entrée,
    la réponse est NON_APPLICABLE : on ne fabrique jamais un trade à partir d'un carnet qui se vide."""
    if not signal_direction:
        return {"confirme": False, "motif": "NON_APPLICABLE_SANS_SIGNAL"}
    preuves = []
    d = _f(depletion_rate)
    if d is not None and d >= float(seuil_depletion):
        preuves.append("FILE_OPPOSEE_SE_VIDE")
    if (_f(volume_traversant) or 0) > 0:
        preuves.append("VOLUME_TRAVERSE")
    if (_f(profondeur_perdue) or 0) > 0:
        preuves.append("PROFONDEUR_DISPARAIT")
    if (_f(cancels_nets) or 0) > 0:
        preuves.append("CANCEL_FLOW_CONFIRME")
    return {"confirme": len(preuves) >= 2, "preuves": preuves, "n_preuves": len(preuves),
            "motif": ("CONFIRME" if len(preuves) >= 2 else "PREUVES_INSUFFISANTES")}


# ─────────────────────── IDEA-60 : flow toxicity causal ───────────────────────
def mid_causal(mids, t_ms: float, *, mode: str = "AVANT"):
    """IDEA-60 — `AVANT` : dernier mid dont ts <= t (état initial). `APRES` : premier mid dont ts >= t
    (markout). Le « nearest timestamp » symétrique est volontairement ABSENT : il choisirait parfois un
    point du futur pour décrire le présent."""
    pts = [(_f(m.get("ts_ms")), _f(m.get("mid"))) for m in (mids or [])]
    pts = [(t, v) for t, v in pts if t is not None and v is not None]
    if mode.upper() == "AVANT":
        passe = [(t, v) for t, v in pts if t <= float(t_ms)]
        return max(passe)[::-1] if passe else (None, None)
    futur = [(t, v) for t, v in pts if t >= float(t_ms)]
    return min(futur)[::-1] if futur else (None, None)


def toxicite_flux(mids, *, t_signal_ms: float, horizon_ms: float, sens: int) -> dict:
    """IDEA-60 — markout causal en bps. Un côté manquant rend UNMEASURABLE (jamais 0)."""
    v0, t0 = mid_causal(mids, t_signal_ms, mode="AVANT")
    v1, t1 = mid_causal(mids, float(t_signal_ms) + float(horizon_ms), mode="APRES")
    if v0 is None or v1 is None or v0 <= 0:
        return {"statut": "UNMEASURABLE", "markout_bps": None,
                "motif": "mid initial ou futur absent — aucun markout fabrique"}
    s = 1 if int(sens) >= 0 else -1
    mk = s * (v1 - v0) / v0 * 1e4
    return {"statut": "OK", "markout_bps": round(mk, 4), "mid_initial": v0, "mid_futur": v1,
            "ts_initial_ms": t0, "ts_futur_ms": t1,
            "toxique": mk < 0}


# ─────────────────────── IDEA-56/57 : ladder passive + inventaire ───────────────────────
def ladder_passive(*, mid: float, spread_bps: float, n_niveaux: int = 3, pas_bps: float = 2.0,
                   taille_par_niveau: float = 100.0, inventaire: float = 0.0,
                   inventaire_max: float = 500.0, skew_max_bps: float = 5.0) -> dict:
    """IDEA-56 — cotations passives multi-niveaux, PAPER uniquement (aucun ordre n'est envoyé nulle part).
    L'inventaire décale les cotations (skew) : plus on est long, plus on baisse pour se délester."""
    m, sp = _f(mid), _f(spread_bps)
    if m is None or sp is None or m <= 0:
        return {"cotations": [], "motif": "MID_OU_SPREAD_INVALIDE", "paper_only": True}
    ratio = max(-1.0, min(1.0, (_f(inventaire) or 0.0) / max(1e-9, float(inventaire_max))))
    skew = -ratio * float(skew_max_bps)                    # long -> skew négatif (on vend plus bas)
    demi = sp / 2.0
    cotations = []
    for i in range(int(n_niveaux)):
        ecart = demi + i * float(pas_bps)
        cotations.append({"niveau": i,
                          "bid": round(m * (1 - (ecart - skew) / 1e4), 8),
                          "ask": round(m * (1 + (ecart + skew) / 1e4), 8),
                          "taille": float(taille_par_niveau)})
    return {"cotations": cotations, "skew_bps": round(skew, 4), "ratio_inventaire": round(ratio, 4),
            "paper_only": True, "aucun_ordre_reel": True}


def risque_inventaire(*, inventaire_usd: float, prix_entree_moyen: float, prix_courant: float,
                      levier: float = 3.0, capital_usd: float = 1000.0,
                      inventaire_max_usd: float = 500.0) -> dict:
    """IDEA-57 — inventaire ouvert, perte latente, concentration et distance de liquidation THÉORIQUE.
    En paper aucune liquidation ne se produit : le chiffre sert d'alerte de risque, pas de prédiction."""
    inv, pe, pc = _f(inventaire_usd), _f(prix_entree_moyen), _f(prix_courant)
    if None in (inv, pe, pc) or pe <= 0:
        return {"statut": "UNMEASURABLE", "motif": "inventaire ou prix invalide"}
    latent = inv * (pc - pe) / pe
    marge = abs(inv) / max(1e-9, float(levier))
    distance = None
    if marge > 0:
        distance = round((marge + latent) / abs(inv) * 1e4, 2) if inv else None
    return {"statut": "OK", "inventaire_usd": round(inv, 6), "pnl_latent_usd": round(latent, 6),
            "marge_immobilisee_usd": round(marge, 6),
            "concentration": round(abs(inv) / max(1e-9, float(capital_usd)), 4),
            "sur_inventaire": abs(inv) > float(inventaire_max_usd),
            "distance_liquidation_theorique_bps": distance,
            "note": "liquidation THEORIQUE — en paper, aucune liquidation reelle"}


__all__ = ["ofi_multi_niveaux", "microprice", "confirmation_depletion", "mid_causal", "toxicite_flux",
           "ladder_passive", "risque_inventaire"]

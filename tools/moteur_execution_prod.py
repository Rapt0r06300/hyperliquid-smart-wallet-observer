"""MOTEUR D'EXÉCUTION PROD-TRUTH (Flo 26/07, LABO-CONTINU-PROD-TRUTH PT-3/PT-6).

Prix RÉELLEMENT exécutables, PnL calculé DIRECTEMENT depuis entry_px/exit_px (jamais mid→mid avec un seul
demi-spread) :
  - taker LONG  : entrée = ASK (on croise), sortie = BID futur exécutable ;
  - taker SHORT : entrée = BID (on croise), sortie = ASK futur exécutable ;
  - maker       : entrée passive (BID pour long, ASK pour short) selon fraction de remplissage.
Le spread est donc PAYÉ dans la différence de prix (jamais soustrait une 2ᵉ fois). On rapporte en plus, de
façon SÉPARÉE : frais (entrée+sortie, profil versionné, coût conservateur si userFees manque), spread effectif,
slippage de profondeur (VWAP par notionnel), impact, funding (sur la durée de détention), latence.

Chaque évaluation renvoie UN OBJET PAR ÉPISODE avec identité stable (episode_id, entry_ts, exit_ts, status).
`evaluer_episodes` renvoie une liste de MÊME longueur que le corpus : UNMEASURABLE / NO_FILL / NO_DATA gardent
leur identité — on ne filtre jamais pour re-zipper ensuite. 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import hashlib

# ─────────── profils de frais VERSIONNÉS (bps par jambe) ───────────
#: maker peut être un rebate (négatif) mais on ne l'exploite pas par défaut (conservateur). taker = payé.
PROFILS_FRAIS = {
    "hl_v1_conservateur": {"maker_bps": 1.0, "taker_bps": 3.5, "source": "conservateur (userFees absents)"},
    "hl_v1_standard":     {"maker_bps": 1.0, "taker_bps": 2.5, "source": "grille HL standard"},
    "hl_v1_vip":          {"maker_bps": 0.0, "taker_bps": 2.0, "source": "grille HL réduite"},
}
PROFIL_DEFAUT = "hl_v1_conservateur"


def frais_par_jambe(profil: str, *, maker: bool, user_fees_bps=None) -> float:
    """bps de frais pour UNE jambe. Si `user_fees_bps` (réel) fourni -> l'utilise ; sinon profil versionné.
    Coût CONSERVATEUR quand la donnée manque (profil conservateur par défaut)."""
    if user_fees_bps is not None:
        try:
            return float(user_fees_bps)
        except (TypeError, ValueError):
            pass
    p = PROFILS_FRAIS.get(profil) or PROFILS_FRAIS[PROFIL_DEFAUT]
    return float(p["maker_bps"] if maker else p["taker_bps"])


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def vwap_profondeur(niveaux, notional_usd: float) -> dict:
    """VWAP pour remplir `notional_usd` en marchant les niveaux [[px, size], ...] (size en unités de base).
    Rend {vwap, rempli_frac, px_top}. Si profondeur insuffisante -> rempli_frac < 1 (honnête)."""
    if not niveaux:
        return {"vwap": None, "rempli_frac": 0.0, "px_top": None}
    px_top = _num(niveaux[0][0])
    besoin = float(notional_usd)
    cout_cum, notion_cum = 0.0, 0.0
    for niv in niveaux:
        px, sz = _num(niv[0]), _num(niv[1])
        if px is None or sz is None or px <= 0 or sz <= 0:
            continue
        notion_dispo = px * sz
        prendre = min(notion_dispo, besoin - notion_cum)
        if prendre <= 0:
            break
        cout_cum += prendre                          # notionnel exécuté à ce niveau
        notion_cum += prendre
        # somme pondérée de 1/px pour reconstruire la quantité, donc le VWAP = notion/qty
        if notion_cum >= besoin - 1e-9:
            break
    # VWAP = Σ notionnel / Σ quantité ; on recompose la quantité en re-marchant
    qty = 0.0
    reste = float(notional_usd)
    for niv in niveaux:
        px, sz = _num(niv[0]), _num(niv[1])
        if px is None or sz is None or px <= 0 or sz <= 0:
            continue
        notion_dispo = px * sz
        prendre = min(notion_dispo, reste)
        if prendre <= 0:
            break
        qty += prendre / px
        reste -= prendre
        if reste <= 1e-9:
            break
    rempli = float(notional_usd) - reste
    vwap = (rempli / qty) if qty > 0 else None
    return {"vwap": vwap, "rempli_frac": round(rempli / float(notional_usd), 6) if notional_usd else 0.0,
            "px_top": px_top}


def _bid_ask(ep):
    bid, ask = _num(ep.get("bid")), _num(ep.get("ask"))
    if bid is None or ask is None or not (ask > bid > 0):
        return None, None
    return bid, ask


def _fwd(ep, cle, horizon_ms):
    d = ep.get(cle) or {}
    return _num(d.get(horizon_ms) if horizon_ms in d else d.get(str(horizon_ms)))


def prix_exit_executable(ep, *, sens: int, horizon_ms: int):
    """Prix de SORTIE exécutable : BID futur pour un long, ASK futur pour un short. Utilise fwd_bid/fwd_ask
    si présents (vrais niveaux futurs), sinon dérive depuis fwd_mid ∓ demi-spread courant (approximation
    documentée). Rend (exit_px, source) ou (None, 'UNMEASURABLE')."""
    fb = _fwd(ep, "fwd_bid", horizon_ms)
    fa = _fwd(ep, "fwd_ask", horizon_ms)
    if fb is not None and fa is not None:
        return (fb if sens > 0 else fa), "FWD_BOOK"
    fmid = _fwd(ep, "fwd_mid", horizon_ms)
    if fmid is None:
        return None, "UNMEASURABLE"
    bid, ask = _bid_ask(ep)
    if bid is None:
        return None, "NO_DATA"
    demi = (ask - bid) / 2.0
    return (fmid - demi if sens > 0 else fmid + demi), "FWD_MID_MOINS_DEMISPREAD"


def evaluer_episode(ep: dict, *, sens: int, horizon_ms: int, modele_exec: str = "taker",
                    notional_usd: float = 100.0, profil: str = PROFIL_DEFAUT) -> dict:
    """UN objet par épisode. status ∈ OK / UNMEASURABLE / NO_FILL / NO_DATA. PnL depuis entry_px/exit_px."""
    coin = ep.get("coin")
    ts = _num(ep.get("ts_ms")) or 0.0
    latence_ms = _num(ep.get("latence_ms")) or 0.0
    eid = ep.get("episode_id") or hashlib.sha256(
        ("%s|%s|%s|%s" % (coin, ts, sens, horizon_ms)).encode()).hexdigest()[:16]
    base = {"episode_id": eid, "coin": coin, "sens": sens, "horizon_ms": horizon_ms,
            "entry_ts": ts + latence_ms, "exit_ts": ts + latence_ms + horizon_ms, "modele": modele_exec}
    bid, ask = _bid_ask(ep)
    if bid is None:
        return {**base, "status": "NO_DATA", "net_bps": None}
    mid = (bid + ask) / 2.0
    maker = modele_exec != "taker"
    # ── ENTRÉE exécutable ──
    if maker:
        entry_px = bid if sens > 0 else ask          # passif : on POSTE du bon côté (économise le spread d'entrée)
    else:
        entry_px = ask if sens > 0 else bid          # taker : on CROISE
    # slippage de profondeur (VWAP par notionnel) si le carnet est fourni
    cote_entree = (ep.get("asks") if sens > 0 else ep.get("bids")) if not maker else None
    if cote_entree:
        vp = vwap_profondeur(cote_entree, notional_usd)
        if vp["vwap"]:
            entry_px = vp["vwap"]
        slippage_bps = abs((entry_px - (vp["px_top"] or entry_px)) / mid) * 1e4
    else:
        slippage_bps = (_num(ep.get("slippage_bps")) or 0.0)
    # ── SORTIE exécutable ──
    exit_px, src_exit = prix_exit_executable(ep, sens=sens, horizon_ms=horizon_ms)
    if exit_px is None:
        return {**base, "status": src_exit if src_exit in ("UNMEASURABLE", "NO_DATA") else "UNMEASURABLE",
                "net_bps": None, "entry_px": round(entry_px, 8)}
    # ── remplissage (maker probabiliste) ──
    if maker:
        from recherche_18h_mecanismes import maker_risk_averse_fill, maker_probabiliste_fill
        f = maker_risk_averse_fill if modele_exec == "maker_risk_averse" else maker_probabiliste_fill
        frac = float(f(_num(ep.get("queue_devant_sz")) or 0.0, _num(ep.get("vol_traversant_sz")) or 0.0))
        if frac <= 0:
            return {**base, "status": "NO_FILL", "net_bps": None, "fill": 0.0,
                    "entry_px": round(entry_px, 8), "exit_px": round(exit_px, 8)}
    else:
        frac = 1.0
    # ── PnL BRUT depuis les prix exécutables (le spread est DÉJÀ payé dans entry/exit) ──
    if sens > 0:
        gross_bps = (exit_px - entry_px) / entry_px * 1e4
    else:
        gross_bps = (entry_px - exit_px) / entry_px * 1e4
    # ── coûts SÉPARÉS au-delà du prix ──
    fee_in = frais_par_jambe(profil, maker=maker, user_fees_bps=ep.get("user_fee_in_bps"))
    fee_out = frais_par_jambe(profil, maker=False, user_fees_bps=ep.get("user_fee_out_bps"))  # sortie taker (conservateur)
    fees_bps = fee_in + fee_out
    impact_bps = _num(ep.get("impact_bps")) or 0.0
    latence_bps = _num(ep.get("latence_bps")) or 0.0
    # funding sur la durée de détention (funding_bps_par_h × heures), signé selon le sens
    fbph = _num(ep.get("funding_bps_par_h"))
    heures = horizon_ms / 3_600_000.0
    funding_bps = (abs(fbph) * heures) if fbph is not None else 0.0   # coût conservateur : on paie le funding
    spread_effectif_bps = (ask - bid) / mid * 1e4                     # transparence (déjà dans le prix)
    net_bps = (gross_bps - fees_bps - slippage_bps - impact_bps - latence_bps - funding_bps) * frac
    return {**base, "status": "OK", "entry_px": round(entry_px, 8), "exit_px": round(exit_px, 8),
            "exit_source": src_exit, "gross_bps": round(gross_bps, 4), "fees_bps": round(fees_bps, 4),
            "spread_bps": round(spread_effectif_bps, 4), "slippage_bps": round(slippage_bps, 4),
            "impact_bps": round(impact_bps, 4), "funding_bps": round(funding_bps, 4),
            "latency_bps": round(latence_bps, 4), "fill": round(frac, 4), "profil_frais": profil,
            "net_bps": round(net_bps, 4)}


def evaluer_episodes(corpus, *, sens: int, horizon_ms: int, modele_exec: str = "taker",
                     notional_usd: float = 100.0, profil: str = PROFIL_DEFAUT) -> list:
    """Liste de MÊME longueur que `corpus` : chaque épisode garde son identité et son status (jamais de
    filtrage-puis-zip)."""
    return [evaluer_episode(ep, sens=sens, horizon_ms=horizon_ms, modele_exec=modele_exec,
                            notional_usd=notional_usd, profil=profil) for ep in corpus]


def nets_mesures(episodes) -> list:
    """Extrait les net_bps des seuls épisodes réellement mesurés (status OK). Les UNMEASURABLE/NO_FILL ne
    deviennent JAMAIS 0."""
    return [o["net_bps"] for o in episodes if o.get("status") == "OK" and o.get("net_bps") is not None]


__all__ = ["PROFILS_FRAIS", "PROFIL_DEFAUT", "frais_par_jambe", "vwap_profondeur", "prix_exit_executable",
           "evaluer_episode", "evaluer_episodes", "nets_mesures"]

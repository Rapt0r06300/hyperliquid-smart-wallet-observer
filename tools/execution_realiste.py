"""EXÉCUTION RÉALISTE — fills partiels, maker/queue, adverse selection, latence, timings (IDEA-14 → 18, 22 → 26).

`moteur_execution_prod` calcule déjà le prix exécutable (IDEA-12) et le VWAP de profondeur (IDEA-13).
Ce module ajoute ce qui manquait pour que le PnL ne soit pas une fiction optimiste :

  • IDEA-14 : un fill à 20 % propage 20 % PARTOUT (position, marge, coûts, PnL, turnover) — jamais 100 % ;
  • IDEA-15 : probabilité de fill MAKER (file devant nous, volume traversant, annulations) + NO_FILL honnête ;
  • IDEA-16 : position dans la file calibrée empiriquement (arrivées, annulations, depletion rate) ;
  • IDEA-17 : adverse selection = markouts 100/250/500 ms, 1 s, 5 s APRÈS le fill ;
  • IDEA-18 : un fill rate élevé n'est PAS une qualité — verdict croisé fill × markout × net ;
  • IDEA-22 : budget de latence complet (7 horodatages) avec p50/p95/p99 ;
  • IDEA-23 : edge decay = edge mesuré en fonction du retard ;
  • IDEA-24 : plusieurs timings d'entrée comparés sur les mêmes données ;
  • IDEA-25 : qualité d'entrée (distance au mid, spread payé, coût break-even) > win-rate brut ;
  • IDEA-26 : win-rate / edge MINIMAL requis pour être rentable après coûts.

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import statistics

#: étapes du budget de latence (IDEA-22), dans l'ordre causal obligatoire.
ETAPES_LATENCE = ("exchange_ts", "recv_ts", "feature_ready_ts", "signal_ts",
                  "decision_ts", "paper_intent_ts", "modeled_fill_ts")

#: horizons de markout pour l'adverse selection (IDEA-17), en millisecondes.
MARKOUTS_MS = (100, 250, 500, 1_000, 5_000)


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ─────────────────────── IDEA-14 : propagation des fills partiels ───────────────────────
def propager_fill_partiel(*, requested_notional: float, filled_notional: float, levier: float = 1.0,
                          couts_bps: dict | None = None, gross_bps: float | None = None) -> dict:
    """Un fill partiel se propage à TOUT (IDEA-14). `fill_fraction = filled/requested` multiplie la position,
    la marge, les coûts en USD, le PnL et le turnover. Aucun de ces champs ne reste au notionnel demandé."""
    req = _num(requested_notional) or 0.0
    fil = max(0.0, min(_num(filled_notional) or 0.0, req))
    if req <= 0:
        return {"statut": "REQUESTED_NOTIONAL_INVALIDE", "fill_fraction": None}
    frac = fil / req
    lev = max(1e-9, _num(levier) or 1.0)
    bps_total = sum(float(v or 0.0) for v in (couts_bps or {}).values())
    couts_usd = fil * bps_total / 1e4                      # coûts sur le notionnel RÉELLEMENT rempli
    pnl_usd = (fil * float(gross_bps) / 1e4) if gross_bps is not None else None
    return {
        "statut": ("NO_FILL" if frac <= 0 else ("PARTIAL_FILL" if frac < 1.0 else "FILL_COMPLET")),
        "fill_fraction": round(frac, 6),
        "requested_notional": round(req, 6), "filled_notional": round(fil, 6),
        "position_notional": round(fil, 6),                 # la position vaut le REMPLI, pas le demandé
        "marge_usd": round(fil / lev, 6),
        "couts_usd": round(couts_usd, 6),
        "pnl_brut_usd": (round(pnl_usd, 6) if pnl_usd is not None else None),
        "pnl_net_usd": (round(pnl_usd - couts_usd, 6) if pnl_usd is not None else None),
        "turnover_usd": round(fil, 6),
    }


# ─────────────────────── IDEA-15/16 : fill maker, file d'attente ───────────────────────
def position_file(*, taille_devant: float, ajouts_devant: float = 0.0, annulations_devant: float = 0.0,
                  volume_traversant: float = 0.0) -> dict:
    """IDEA-16 — position dans la file, calibrée sur des grandeurs OBSERVÉES : taille devant nous, ajouts
    (qui ne nous doublent pas au même prix), annulations devant (qui nous font avancer) et volume traversant
    (qui consomme la file). `depletion_rate` = part de la file initiale déjà consommée."""
    devant0 = max(0.0, _num(taille_devant) or 0.0)
    annul = max(0.0, _num(annulations_devant) or 0.0)
    vol = max(0.0, _num(volume_traversant) or 0.0)
    devant = max(0.0, devant0 + max(0.0, _num(ajouts_devant) or 0.0) - annul - vol)
    consomme = max(0.0, devant0 - devant)
    return {"queue_ahead_initial": devant0, "queue_ahead": devant,
            "queue_consommee": consomme,
            "queue_depletion_rate": (round(consomme / devant0, 6) if devant0 > 0 else None)}


def probabilite_fill_maker(*, taille_devant: float, notre_taille: float, volume_traversant: float,
                           ajouts_devant: float = 0.0, annulations_devant: float = 0.0) -> dict:
    """IDEA-15 — probabilité de fill maker et fraction remplie. Le volume traversant sert d'abord la file
    DEVANT nous ; seul le reliquat nous remplit. Si rien ne dépasse : NO_FILL honnête (jamais un fill offert)."""
    q = position_file(taille_devant=taille_devant, ajouts_devant=ajouts_devant,
                      annulations_devant=annulations_devant, volume_traversant=volume_traversant)
    notre = max(0.0, _num(notre_taille) or 0.0)
    vol = max(0.0, _num(volume_traversant) or 0.0)
    devant0 = q["queue_ahead_initial"] + max(0.0, _num(ajouts_devant) or 0.0) - max(0.0, _num(annulations_devant) or 0.0)
    reliquat = max(0.0, vol - max(0.0, devant0))            # ce qui nous atteint réellement
    rempli = min(notre, reliquat)
    frac = (rempli / notre) if notre > 0 else None
    return {**q, "notre_taille": notre, "filled_size": rempli,
            "filled_fraction": (round(frac, 6) if frac is not None else None),
            "fill_probability": (round(frac, 6) if frac is not None else None),
            "statut": ("NO_FILL" if not rempli else ("PARTIAL_FILL" if rempli < notre else "FILL_COMPLET"))}


# ─────────────────────── IDEA-17/18 : adverse selection, qualité du fill ───────────────────────
def markouts_apres_fill(prix_fill: float, *, sens: int, mids_futurs: dict) -> dict:
    """IDEA-17 — markouts causaux APRÈS le fill : (mid_futur - prix_fill) * sens, en bps. Un horizon sans
    donnée reste None (UNMEASURABLE), jamais 0. `adverse_selection_bps` = -markout court (ce que le marché
    nous a repris juste après)."""
    p = _num(prix_fill)
    s = 1 if int(sens) >= 0 else -1
    out = {}
    for h in MARKOUTS_MS:
        m = _num((mids_futurs or {}).get(h))
        out["markout_%dms_bps" % h] = (round(s * (m - p) / p * 1e4, 4) if (p and m) else None)
    court = out.get("markout_100ms_bps")
    if court is None:
        court = out.get("markout_250ms_bps")
    return {**out, "adverse_selection_bps": (round(-court, 4) if court is not None else None),
            "mesurable": any(v is not None for v in out.values())}


def qualite_fill(*, fill_rate: float, markout_bps: float | None, net_bps: float | None) -> dict:
    """IDEA-18 — un fill rate élevé n'est PAS une qualité. Verdict croisé : on n'accepte que si le markout
    n'est pas franchement défavorable ET que le net après coûts est positif."""
    fr = _num(fill_rate)
    mk, net = _num(markout_bps), _num(net_bps)
    if net is None or mk is None:
        return {"verdict": "UNMEASURABLE", "pourquoi": "markout ou net manquant", "fill_rate": fr}
    if net <= 0:
        return {"verdict": "MAUVAIS_NET", "pourquoi": "net apres couts <= 0 malgre fill_rate=%s" % fr,
                "fill_rate": fr, "net_bps": net, "markout_bps": mk}
    if mk < 0:
        return {"verdict": "FILL_TOXIQUE", "pourquoi": "on est rempli quand le marche part contre nous",
                "fill_rate": fr, "net_bps": net, "markout_bps": mk}
    return {"verdict": "OK", "pourquoi": "fill + markout + net coherents",
            "fill_rate": fr, "net_bps": net, "markout_bps": mk}


# ─────────────────────── IDEA-22 : budget complet de latence ───────────────────────
def budget_latence(horodatages: dict) -> dict:
    """IDEA-22 — décompose exchange_ts → recv_ts → feature_ready_ts → signal_ts → decision_ts →
    paper_intent_ts → modeled_fill_ts. Une étape manquante donne None (jamais 0). Une étape en arrière
    dans le temps est signalée : la causalité est violée."""
    ts = {e: _num((horodatages or {}).get(e)) for e in ETAPES_LATENCE}
    segments, violations = {}, []
    precedent_nom, precedent = None, None
    for nom in ETAPES_LATENCE:
        v = ts[nom]
        if v is None:
            continue
        if precedent is not None:
            d = v - precedent
            segments["%s->%s" % (precedent_nom, nom)] = round(d, 4)
            if d < 0:
                violations.append("%s AVANT %s" % (nom, precedent_nom))
        precedent_nom, precedent = nom, v
    total = None
    if ts["exchange_ts"] is not None and ts["modeled_fill_ts"] is not None:
        total = round(ts["modeled_fill_ts"] - ts["exchange_ts"], 4)
    return {"segments_ms": segments, "total_ms": total, "violations_causalite": violations,
            "complet": all(ts[e] is not None for e in ETAPES_LATENCE), "horodatages": ts}


def percentiles_latence(totaux_ms) -> dict:
    """p50/p95/p99 du budget de latence (IDEA-22). Rend None si l'échantillon est vide (jamais 0)."""
    xs = sorted(float(x) for x in (totaux_ms or []) if _num(x) is not None)
    if not xs:
        return {"n": 0, "p50": None, "p95": None, "p99": None}
    def q(p):
        if len(xs) == 1:
            return xs[0]
        i = (len(xs) - 1) * p
        b, h = int(i), min(int(i) + 1, len(xs) - 1)
        return round(xs[b] + (xs[h] - xs[b]) * (i - b), 4)
    return {"n": len(xs), "p50": q(0.50), "p95": q(0.95), "p99": q(0.99)}


# ─────────────────────── IDEA-23/24 : edge decay, timings d'entrée ───────────────────────
def edge_decay(edges_par_retard: dict) -> dict:
    """IDEA-23 — edge (bps) mesuré à +50/100/250/500 ms, +1 s, +5 s. Rend la demi-vie observée : le premier
    retard où l'edge tombe sous la moitié de l'edge immédiat. Aucun modèle imposé : c'est une mesure."""
    pts = sorted(((float(k), _num(v)) for k, v in (edges_par_retard or {}).items() if _num(v) is not None))
    if not pts:
        return {"mesurable": False, "motif": "aucun edge mesure"}
    e0 = pts[0][1]
    demi = next((r for r, e in pts if e0 > 0 and e < e0 / 2.0), None)
    return {"mesurable": True, "edge_immediat_bps": round(e0, 4),
            "courbe": [{"retard_ms": r, "edge_bps": round(e, 4)} for r, e in pts],
            "demi_vie_ms": demi,
            "survit_a_500ms": next((e > 0 for r, e in pts if r >= 500), None)}


def comparer_timings(resultats_par_timing: dict, *, min_n: int = 30) -> dict:
    """IDEA-24 — compare plusieurs timings d'entrée sur LES MÊMES données. Un timing avec trop peu
    d'observations est NON_CONCLUANT (jamais élu meilleur par chance)."""
    lignes = []
    for nom, r in (resultats_par_timing or {}).items():
        nets = [float(x) for x in (r.get("nets_bps") or []) if _num(x) is not None]
        n = len(nets)
        lignes.append({"timing": nom, "n": n,
                       "net_median_bps": (round(statistics.median(nets), 4) if nets else None),
                       "concluant": n >= int(min_n)})
    concluants = [l for l in lignes if l["concluant"] and l["net_median_bps"] is not None]
    meilleur = max(concluants, key=lambda l: l["net_median_bps"]) if concluants else None
    return {"lignes": sorted(lignes, key=lambda l: -(l["net_median_bps"] or -1e9)),
            "meilleur": meilleur, "n_non_concluants": sum(1 for l in lignes if not l["concluant"])}


# ─────────────────────── IDEA-25/26 : qualité d'entrée, break-even ───────────────────────
def qualite_entree(*, prix_entree: float, mid: float, bid: float, ask: float,
                   couts_bps: dict | None = None) -> dict:
    """IDEA-25 — qualité RÉELLE de l'entrée : distance au mid, part du spread payée, coût break-even.
    Un prix meilleur que le mid n'est pas un cadeau : il signale souvent qu'on est du mauvais côté."""
    p, m, b, a = _num(prix_entree), _num(mid), _num(bid), _num(ask)
    if None in (p, m, b, a) or m <= 0 or a <= b:
        return {"mesurable": False, "motif": "prix ou carnet invalide"}
    spread_bps = (a - b) / m * 1e4
    dist_mid_bps = (p - m) / m * 1e4
    part_spread = abs(p - m) / ((a - b) / 2.0) if a > b else None
    be = seuil_break_even(couts_bps or {})
    return {"mesurable": True, "spread_bps": round(spread_bps, 4),
            "distance_mid_bps": round(dist_mid_bps, 4),
            "part_du_spread_payee": (round(part_spread, 4) if part_spread is not None else None),
            "cout_break_even_bps": be["cout_total_bps"],
            "edge_minimal_requis_bps": be["edge_minimal_bps"]}


def seuil_break_even(couts_bps: dict, *, gain_moyen_bps: float | None = None,
                     perte_moyenne_bps: float | None = None) -> dict:
    """IDEA-26 — edge minimal et win-rate minimal requis compte tenu de TOUS les coûts (aller-retour).
    Sans gain/perte moyens fournis, on rend l'edge minimal ; le win-rate requis reste None (non calculable)."""
    total = sum(float(v or 0.0) for v in (couts_bps or {}).values())
    g, p = _num(gain_moyen_bps), _num(perte_moyenne_bps)
    wr = None
    if g is not None and p is not None and (g + p) > 0:
        wr = (p + total) / (g + p)                          # p*(1-wr) + total = g*wr  ->  seuil de rentabilité
        wr = round(min(1.0, max(0.0, wr)), 6)
    return {"cout_total_bps": round(total, 4), "edge_minimal_bps": round(total, 4),
            "win_rate_minimal": wr,
            "atteignable": (None if wr is None else wr < 1.0)}


__all__ = ["ETAPES_LATENCE", "MARKOUTS_MS", "propager_fill_partiel", "position_file",
           "probabilite_fill_maker", "markouts_apres_fill", "qualite_fill", "budget_latence",
           "percentiles_latence", "edge_decay", "comparer_timings", "qualite_entree", "seuil_break_even"]

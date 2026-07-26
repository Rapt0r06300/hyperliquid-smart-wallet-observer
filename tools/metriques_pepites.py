"""MÉTRIQUES QUI DÉBLOQUENT LES PÉPITES (Flo 26/07, UF-3 + AF-P0). Calculées RÉELLEMENT quand les données le
permettent, sinon honnêtement None. Corrections P0 :

- plateau_parametres : rejoue les VOISINS DE PARAMÈTRES du candidat (seuil-2..+2) via le prédicat de la
  famille — une vraie zone stable de paramètres. Distinct de `stabilite_horizons` (les horizons voisins).
  Si la famille n'a pas de paramètre actif (prédicat no-op), plateau_parametres = None (PAS_DE_PARAMETRE_ACTIF).
- concentration : rejoue EXACTEMENT le même signal filtré (famille+features+prédicat+paramètres+direction+
  horizon+régime) sur les autres coins ; jamais un rendement de prix générique.
- capacite : n'est calculable que si les vrais niveaux L2 existent à l'entrée ET à la sortie ; sinon
  capacite_non_nulle = None, motif = DATA_MISSING_L2. N'utilise aucun résultat APPROXIMATE.

Tout `evaluer_*` reçu ne rend QUE des nets PROMOUVABLES (status OK + promotable + exit_source FWD_BOOK). 0 ordre.
"""
from __future__ import annotations

import statistics


# ─────────── plateau de PARAMÈTRES (le vrai) ───────────
def plateau_parametres(*, seuil, evaluer_seuil, famille_a_predicat: bool, largeur: int = 2) -> dict:
    """Rejoue seuil-largeur..seuil+largeur via le prédicat de la famille. Mesure signe conservé, dispersion,
    largeur de la zone positive, dégradation autour du centre, nb de voisins mesurables."""
    if not famille_a_predicat or seuil is None:
        return {"plateau_parametres": None, "motif": "PAS_DE_PARAMETRE_ACTIF"}
    s0 = int(seuil)
    courbe = {}
    for s in range(s0 - largeur, s0 + largeur + 1):
        if s < 1:
            continue
        nets = evaluer_seuil(s)
        courbe[s] = (statistics.median(nets) if nets else None)
    mesures = [(s, v) for s, v in sorted(courbe.items()) if v is not None]
    if len(mesures) < 3:
        return {"plateau_parametres": None, "motif": "VOISINS_INSUFFISANTS", "n_voisins": len(mesures)}
    vals = [v for _, v in mesures]
    signe_ok = all(v > 0 for v in vals) or all(v < 0 for v in vals)
    disp = statistics.pstdev(vals) / (abs(statistics.fmean(vals)) + 1e-9)
    zone_positive = sum(1 for v in vals if v > 0)
    centre = courbe.get(s0)
    degradation = None
    if centre is not None and centre != 0:
        bords = [v for s, v in mesures if s != s0]
        degradation = round((centre - statistics.fmean(bords)) / abs(centre), 3) if bords else None
    return {"plateau_parametres": bool(signe_ok and disp < 1.0 and zone_positive >= 3),
            "signe_conserve": signe_ok, "dispersion_relative": round(disp, 3),
            "largeur_zone_positive": zone_positive, "degradation_centre": degradation,
            "n_voisins": len(mesures), "courbe": courbe}


# ─────────── stabilité sur les HORIZONS (métrique SÉPARÉE, jamais le plateau de paramètres) ───────────
def _horizons_presents(corpus, autour_de: int, k: int = 5) -> list:
    hs = set()
    for e in corpus[:3000]:
        for cle in (e.get("fwd_bid") or e.get("fwd_mid") or {}):
            try:
                hs.add(int(cle))
            except (TypeError, ValueError):
                continue
    if autour_de not in hs and hs:
        hs.add(autour_de)
    return sorted(hs, key=lambda h: abs(h - autour_de))[:k]


def stabilite_horizons(corpus, *, sens: int, horizon_ms: int, evaluer_nets) -> dict:
    """Stabilité du signe/dispersion sur les horizons voisins RÉELLEMENT présents (métrique distincte)."""
    hs = _horizons_presents(corpus, horizon_ms)
    courbe = {}
    for h in hs:
        nets = evaluer_nets(corpus, sens, h)
        if nets:
            courbe[h] = statistics.median(nets)
    vals = [v for v in courbe.values() if v is not None]
    if len(vals) < 3:
        return {"stabilite_horizons": None, "motif": "HORIZONS_INSUFFISANTS", "n_horizons": len(vals)}
    signe_ok = all(v > 0 for v in vals) or all(v < 0 for v in vals)
    disp = statistics.pstdev(vals) / (abs(statistics.fmean(vals)) + 1e-9)
    return {"stabilite_horizons": bool(signe_ok and disp < 1.0), "signe_conserve": signe_ok,
            "dispersion_relative": round(disp, 3), "n_horizons": len(vals), "courbe": courbe}


# ─────────── concentration : MÊME signal filtré sur les autres coins ───────────
def concentration_reelle(*, coins, evaluer_coin) -> dict:
    """`evaluer_coin(coin)` -> nets PROMOUVABLES du MÊME signal (famille+prédicat+params+dir+horizon+régime)
    filtré sur ce coin. un_seul_coin_dominant = un coin porte > 60% du |net| agrégé (ou un seul coin exploitable)."""
    contrib = {}
    for c in coins:
        nets = evaluer_coin(c)
        if nets:
            contrib[c] = statistics.median(nets)
    if not contrib:
        return {"un_seul_coin_dominant": None, "motif": "AUCUN_COIN", "n_coins": 0}
    total = sum(abs(v) for v in contrib.values()) or 1e-9
    parts = {c: abs(v) / total for c, v in contrib.items()}
    domine = (len(contrib) <= 1) or (max(parts.values()) > 0.60)
    return {"un_seul_coin_dominant": bool(domine), "n_coins": len(contrib),
            "part_max": round(max(parts.values()), 3), "contribution": {c: round(v, 3) for c, v in contrib.items()}}


# ─────────── capacité : exige un vrai L2 (sinon DATA_MISSING_L2) ───────────
def _a_l2_reel(corpus, *, horizon_ms: int) -> bool:
    """Vrai L2 requis : profondeur (bids/asks) à l'entrée ET carnet FUTUR (fwd_bid/fwd_ask) à la sortie."""
    for e in corpus[:500]:
        entree_ok = bool(e.get("bids") and e.get("asks"))
        fb, fa = (e.get("fwd_bid") or {}), (e.get("fwd_ask") or {})
        sortie_ok = (horizon_ms in fb or str(horizon_ms) in fb) and (horizon_ms in fa or str(horizon_ms) in fa)
        if entree_ok and sortie_ok:
            return True
    return False


def capacite_reelle(corpus, *, sens: int, horizon_ms: int, courbe_capacite, notional_utile: float = 100.0) -> dict:
    """Capacité via profondeur/VWAP/fills/impact (jamais l'IC, jamais un APPROXIMATE). Sans L2 réel à l'entrée
    ET à la sortie -> capacite_non_nulle = None, motif = DATA_MISSING_L2."""
    if not _a_l2_reel(corpus, horizon_ms=horizon_ms):
        return {"capacite_non_nulle": None, "motif": "DATA_MISSING_L2"}
    courbe = courbe_capacite(corpus, sens=sens, horizon_ms=horizon_ms)
    point = next((p for p in courbe if p["notional_usd"] >= notional_utile and p.get("net_median_bps") is not None), None)
    if point is None:
        point = next((p for p in reversed(courbe) if p.get("net_median_bps") is not None), None)
    if point is None:
        return {"capacite_non_nulle": None, "motif": "PAS_DE_POINT_MESURABLE", "courbe": courbe}
    return {"capacite_non_nulle": bool(point["net_median_bps"] > 0), "notional_teste": point["notional_usd"],
            "net_au_notionnel_bps": point["net_median_bps"], "courbe": courbe}


#: statuts simples pour Flo (progression d'une piste).
STATUTS_SIMPLES = {
    "IDEE": "💡 IDÉE TROUVÉE", "TEST": "🧪 TEST EN COURS", "PREMIER_OK": "⚡ PREMIER TEST RÉUSSI",
    "PEPITE_POSSIBLE": "⭐ PÉPITE POSSIBLE", "A_CONFIRMER": "🔎 À CONFIRMER",
    "POSITIVE_SIM": "✅ POSITIVE EN SIMULATION", "MEILLEURE": "🏆 MEILLEURE PISTE",
    "REJETEE": "❌ REJETÉE", "MANQUE_DONNEES": "⚠ MANQUE DE DONNÉES",
}


def statut_simple(verdict: str, *, net_bps=None) -> str:
    v = (verdict or "").upper()
    if v == "PASS_FORWARD_PAPER":
        return STATUTS_SIMPLES["MEILLEURE"] if (net_bps or 0) > 0 else STATUTS_SIMPLES["POSITIVE_SIM"]
    if v == "DATA_MISSING":
        return STATUTS_SIMPLES["MANQUE_DONNEES"]
    if v == "SHADOW":
        return STATUTS_SIMPLES["A_CONFIRMER"]
    if v == "RESEARCH_ONLY":
        return STATUTS_SIMPLES["PREMIER_OK"]
    return STATUTS_SIMPLES["REJETEE"]


__all__ = ["plateau_parametres", "stabilite_horizons", "concentration_reelle", "capacite_reelle",
           "STATUTS_SIMPLES", "statut_simple"]

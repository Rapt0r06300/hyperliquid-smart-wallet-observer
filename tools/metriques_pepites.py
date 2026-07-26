"""MÉTRIQUES QUI DÉBLOQUENT LES PÉPITES (Flo 26/07, UF-3). Les champs plateau / concentration coin / capacité
restaient `None` -> tout candidat positif ressortait DATA_MISSING. On les CALCULE réellement quand les données
le permettent, sinon on reste honnêtement None (DATA_MISSING). Rien de fabriqué. 0 réseau, 0 ordre.

- plateau       : on rejoue les HORIZONS voisins présents dans la donnée et on exige une zone stable (signe
                  conservé + dispersion bornée) — le moteur différencie réellement par horizon.
- concentration : on teste le candidat sur plusieurs coins et on mesure la contribution de chaque coin ;
                  un_seul_coin_dominant = un coin porte > 60% du |net| total (ou un seul coin disponible).
- capacité      : via la courbe de capacité (profondeur/VWAP/fills/impact), net encore positif à taille utile.
"""
from __future__ import annotations

import statistics


def _horizons_presents(corpus, autour_de: int, k: int = 5) -> list:
    """Horizons réellement mesurables (présents dans fwd_mid) les plus proches de `autour_de`."""
    hs = set()
    for e in corpus[:3000]:
        for cle in (e.get("fwd_mid") or {}):
            try:
                hs.add(int(cle))
            except (TypeError, ValueError):
                continue
    if autour_de not in hs and hs:
        hs.add(autour_de)
    return sorted(hs, key=lambda h: abs(h - autour_de))[:k]


def plateau_reel(corpus, *, sens: int, horizon_ms: int, evaluer_nets) -> dict:
    """Rejoue les horizons voisins RÉELLEMENT présents et mesure la stabilité. `evaluer_nets(corpus, sens, h)`
    -> liste de net mesurés. plateau True si >=3 horizons, même signe, dispersion relative < 1."""
    hs = _horizons_presents(corpus, horizon_ms)
    courbe = {}
    for h in hs:
        nets = evaluer_nets(corpus, sens, h)
        if nets:
            courbe[h] = statistics.median(nets)
    vals = [v for v in courbe.values() if v is not None]
    if len(vals) < 3:
        return {"plateau": None, "motif": "HORIZONS_INSUFFISANTS", "n_horizons": len(vals)}
    signe_ok = all(v > 0 for v in vals) or all(v < 0 for v in vals)
    disp = statistics.pstdev(vals) / (abs(statistics.fmean(vals)) + 1e-9)
    return {"plateau": bool(signe_ok and disp < 1.0), "signe_conserve": signe_ok,
            "dispersion_relative": round(disp, 3), "n_horizons": len(vals), "courbe": courbe}


def concentration_reelle(corpus, *, sens: int, horizon_ms: int, coins, filtrer, evaluer_nets) -> dict:
    """Teste le candidat sur PLUSIEURS coins et mesure la contribution de chacun. un_seul_coin_dominant = un
    coin porte plus de 60% du |net| agrégé (ou un seul coin exploitable)."""
    contrib = {}
    for c in coins:
        nets = evaluer_nets(filtrer(corpus, coin=c), sens, horizon_ms)
        if nets:
            contrib[c] = statistics.median(nets)
    if not contrib:
        return {"un_seul_coin_dominant": None, "motif": "AUCUN_COIN", "n_coins": 0}
    total = sum(abs(v) for v in contrib.values()) or 1e-9
    parts = {c: abs(v) / total for c, v in contrib.items()}
    domine = (len(contrib) <= 1) or (max(parts.values()) > 0.60)
    return {"un_seul_coin_dominant": bool(domine), "n_coins": len(contrib),
            "part_max": round(max(parts.values()), 3), "contribution": {c: round(v, 3) for c, v in contrib.items()}}


def capacite_reelle(corpus, *, sens: int, horizon_ms: int, courbe_capacite, notional_utile: float = 100.0) -> dict:
    """Capacité via la courbe de capacité (profondeur/VWAP/fills/impact), PAS l'intervalle de confiance.
    capacite_non_nulle = net médian encore > 0 au notionnel utile."""
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
    """Traduit un verdict technique en statut simple pour Flo."""
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


__all__ = ["plateau_reel", "concentration_reelle", "capacite_reelle", "STATUTS_SIMPLES", "statut_simple"]

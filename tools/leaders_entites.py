"""SMART WALLETS, VAULTS, METAORDERS (IDEA-61 → 66).

Loi mesurée du projet : la copie globale est réfutée (−7,97 bps sur 24 133 signaux OOS, cause = leader
CONTRARIEN). Ce module n'essaie donc pas de « faire marcher la copie » : il fournit les outils qui
permettent de **ne pas se raconter d'histoire** sur les leaders.

  • IDEA-61 : classer l'entité (TRADER / VAULT / MARKET_MAKER / TWAP_METAORDER / PROTOCOL_INFRA /
    UNKNOWN) — une infrastructure non copiable ne doit jamais être appelée « smart wallet » ;
  • IDEA-62 : copyabilité POINT-IN-TIME (fraîcheur du fill, latence de détection, taille, profondeur,
    coût de copie, concentration, durée de position, suivabilité de la sortie) ;
  • IDEA-63 : détection metaorder/TWAP (regroupement des fills, stade d'exécution, flux résiduel,
    crowding, risque d'arriver trop tard) ;
  • IDEA-64 : lead-lag CONDITIONNÉ (par coin, horizon, régime, horloge) — jamais une moyenne globale ;
  • IDEA-65 : cohortes de leaders comparées entre elles ;
  • IDEA-66 : leaders en conflit = AUCUN signal par défaut.

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import statistics

TRADER = "TRADER"
VAULT = "VAULT"
MARKET_MAKER = "MARKET_MAKER"
TWAP_METAORDER = "TWAP_METAORDER"
PROTOCOL_INFRA = "PROTOCOL_INFRA"
UNKNOWN = "UNKNOWN"
TYPES_ENTITE = (TRADER, VAULT, MARKET_MAKER, TWAP_METAORDER, PROTOCOL_INFRA, UNKNOWN)

#: entités NON copiables : les suivre n'a aucun sens économique.
NON_COPIABLES = (MARKET_MAKER, PROTOCOL_INFRA, UNKNOWN)


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def classer_entite(*, n_fills: int = 0, ratio_maker: float | None = None, deux_sens_simultanes: bool = False,
                   cadence_reguliere: bool = False, est_vault_declare: bool = False,
                   duree_moyenne_position_ms: float | None = None) -> dict:
    """IDEA-61 — classification explicite et son corollaire : `copiable`. Un market maker qui cote des deux
    côtés n'est pas un directionnel ; le copier revient à copier du bruit."""
    if est_vault_declare:
        t, pourquoi = VAULT, "vault declare"
    elif deux_sens_simultanes and (ratio_maker is None or (_f(ratio_maker) or 0) > 0.7):
        t, pourquoi = MARKET_MAKER, "cote des deux cotes, majoritairement maker"
    elif cadence_reguliere and n_fills >= 5:
        t, pourquoi = TWAP_METAORDER, "fills reguliers = execution programmee"
    elif n_fills <= 0:
        t, pourquoi = UNKNOWN, "aucun fill observe"
    elif duree_moyenne_position_ms is not None and (_f(duree_moyenne_position_ms) or 0) < 1_000:
        t, pourquoi = MARKET_MAKER, "positions ultra-courtes = tenue de marche"
    else:
        t, pourquoi = TRADER, "directionnel apparent"
    return {"type": t, "pourquoi": pourquoi, "copiable": t not in NON_COPIABLES,
            "avertissement": ("entite NON copiable — ne pas l'appeler smart wallet"
                              if t in NON_COPIABLES else None)}


def copyabilite(*, age_fill_ms=None, latence_detection_ms=None, taille_usd=None, profondeur_usd=None,
                cout_copie_bps=None, concentration=None, duree_position_ms=None,
                sortie_observable: bool | None = None, age_max_ms: float = 30_000.0) -> dict:
    """IDEA-62 — copyabilité POINT-IN-TIME : ce qu'on savait À L'INSTANT du fill, pas après coup.
    Chaque critère manquant est INCONNU et pénalise le verdict (deny-by-default)."""
    criteres, inconnus = {}, []
    def _c(nom, ok):
        if ok is None:
            inconnus.append(nom)
        criteres[nom] = ok
    a = _f(age_fill_ms)
    _c("fill_frais", None if a is None else a <= float(age_max_ms))
    _c("detection_rapide", None if _f(latence_detection_ms) is None else _f(latence_detection_ms) <= 5_000.0)
    t, p = _f(taille_usd), _f(profondeur_usd)
    _c("taille_absorbable", None if (t is None or p is None) else t <= p)
    c = _f(cout_copie_bps)
    _c("cout_copie_raisonnable", None if c is None else c <= 15.0)
    k = _f(concentration)
    _c("pas_trop_concentre", None if k is None else k <= 0.5)
    d = _f(duree_position_ms)
    _c("position_assez_longue", None if d is None else d >= 10_000.0)
    _c("sortie_suivable", sortie_observable)
    verts = [v for v in criteres.values() if v is True]
    return {"criteres": criteres, "inconnus": inconnus,
            "score": (round(len(verts) / len(criteres), 4) if criteres else None),
            "copiable": (not inconnus) and all(criteres.values()),
            "motif": ("OK" if (not inconnus and all(criteres.values()))
                      else ("CRITERES_INCONNUS:%s" % ",".join(inconnus) if inconnus else "CRITERES_NON_REMPLIS"))}


def detecter_metaorder(fills, *, fenetre_ms: float = 60_000.0, min_fills: int = 3,
                       tolerance_cadence: float = 0.35) -> dict:
    """IDEA-63 — regroupe les fills d'un même wallet/coin/direction et estime s'il s'agit d'une exécution
    programmée (TWAP). Rend le stade d'exécution et le flux résiduel : arriver au stade 0.9 signifie qu'il
    ne reste presque rien à porter le prix — donc qu'on arrive trop tard."""
    fs = sorted([f for f in (fills or []) if _f(f.get("ts_ms")) is not None], key=lambda f: float(f["ts_ms"]))
    if len(fs) < int(min_fills):
        return {"metaorder": False, "motif": "TROP_PEU_DE_FILLS", "n_fills": len(fs)}
    t0, t1 = float(fs[0]["ts_ms"]), float(fs[-1]["ts_ms"])
    ecarts = [float(fs[i + 1]["ts_ms"]) - float(fs[i]["ts_ms"]) for i in range(len(fs) - 1)]
    moy = statistics.fmean(ecarts) if ecarts else 0.0
    cv = (statistics.pstdev(ecarts) / moy) if (ecarts and moy > 0) else None
    reguliere = bool(cv is not None and cv <= float(tolerance_cadence))
    total = sum(abs(_f(f.get("size_usd")) or 0.0) for f in fs)
    cumule = 0.0
    stades = []
    for f in fs:
        cumule += abs(_f(f.get("size_usd")) or 0.0)
        stades.append(round(cumule / total, 4) if total else None)
    stade = stades[-1] if stades else None
    return {"metaorder": reguliere, "n_fills": len(fs), "duree_ms": round(t1 - t0, 2),
            "cadence_moyenne_ms": round(moy, 2), "coefficient_variation": (round(cv, 4) if cv is not None else None),
            "cadence_reguliere": reguliere,
            "taille_totale_usd": round(total, 2),
            "stade_execution": stade,
            "flux_residuel_estime": (round(1.0 - stade, 4) if stade is not None else None),
            "trop_tard": (stade is not None and stade >= 0.8),
            "avertissement": ("stade avance : l'essentiel du flux est deja passe" if (stade or 0) >= 0.8 else None)}


def lead_lag_conditionne(observations, *, min_n: int = 30) -> dict:
    """IDEA-64 — lead-lag ventilé par (coin, horizon, régime, horloge). Une moyenne globale masque les
    signes opposés ; un sous-groupe sous `min_n` est NON_CONCLUANT."""
    groupes = {}
    for o in (observations or []):
        cle = (o.get("coin"), o.get("horizon_ms"), o.get("regime"), o.get("horloge"))
        v = _f(o.get("edge_bps"))
        if v is not None:
            groupes.setdefault(cle, []).append(v)
    lignes = []
    for cle, xs in groupes.items():
        lignes.append({"coin": cle[0], "horizon_ms": cle[1], "regime": cle[2], "horloge": cle[3],
                       "n": len(xs), "edge_median_bps": round(statistics.median(xs), 4),
                       "concluant": len(xs) >= int(min_n)})
    concluants = [l for l in lignes if l["concluant"]]
    positifs = [l for l in concluants if l["edge_median_bps"] > 0]
    return {"lignes": sorted(lignes, key=lambda l: -(l["edge_median_bps"])),
            "n_groupes": len(lignes), "n_concluants": len(concluants), "n_positifs": len(positifs),
            "avertissement": "une moyenne globale masquerait des signes opposes"}


def comparer_cohortes(nets_par_cohorte: dict, *, min_n: int = 30) -> dict:
    """IDEA-65 — compare vaults / whales / MM / directionnels / nouveaux / persistants sur le MÊME moteur."""
    lignes = []
    for nom, nets in (nets_par_cohorte or {}).items():
        xs = [float(x) for x in (nets or []) if isinstance(x, (int, float))]
        lignes.append({"cohorte": nom, "n": len(xs),
                       "net_median_bps": (round(statistics.median(xs), 4) if xs else None),
                       "concluant": len(xs) >= int(min_n)})
    return {"lignes": sorted(lignes, key=lambda l: -(l["net_median_bps"] or -1e9)),
            "meilleure": next((l["cohorte"] for l in sorted(lignes, key=lambda l: -(l["net_median_bps"] or -1e9))
                               if l["concluant"] and (l["net_median_bps"] or 0) > 0), None)}


def resoudre_conflit(signaux_leaders) -> dict:
    """IDEA-66 — deux leaders opposés sur le même coin = CONFLIT. Par défaut : AUCUN signal. On ne choisit
    pas « le plus gros » ni « le plus rapide » sans preuve OOS que celui-là est réellement informatif."""
    sens = {}
    for s in (signaux_leaders or []):
        d = s.get("direction")
        if d in (1, -1):
            sens.setdefault(int(d), []).append(s.get("leader"))
    if not sens:
        return {"signal": None, "motif": "AUCUN_SIGNAL"}
    if len(sens) > 1:
        return {"signal": None, "conflit": True, "motif": "LEADERS_OPPOSES_AUCUN_SIGNAL_PAR_DEFAUT",
                "longs": sens.get(1, []), "shorts": sens.get(-1, []),
                "action": "mesurer OOS lequel est informatif avant de trancher"}
    d = next(iter(sens))
    return {"signal": d, "conflit": False, "leaders": sens[d], "motif": "CONSENSUS"}


__all__ = ["TYPES_ENTITE", "TRADER", "VAULT", "MARKET_MAKER", "TWAP_METAORDER", "PROTOCOL_INFRA",
           "UNKNOWN", "NON_COPIABLES", "classer_entite", "copyabilite", "detecter_metaorder",
           "lead_lag_conditionne", "comparer_cohortes", "resoudre_conflit"]

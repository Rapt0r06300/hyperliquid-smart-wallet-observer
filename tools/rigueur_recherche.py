"""RIGUEUR DE LA RECHERCHE — étages, multiple testing, benchmarks, ablation, simplicité (IDEA-41 → 51).

`validation_18h` fournit déjà walk-forward + purge/embargo (43), bootstrap-bloc (47), placebos (48),
stabilité des paramètres (51 partiel) et le gate PASS/KILL. Ce module ajoute la DISCIPLINE autour :

  • IDEA-41 : le workflow en étages est explicite et ORDONNÉ — on ne saute jamais une étape ;
  • IDEA-42 : un résultat FAST_SCREEN n'est jamais promouvable sans EXACT_REPLAY ;
  • IDEA-44 : le nombre d'essais EFFECTIF compte TOUTES les dimensions explorées (coins, horizons, seuils,
    stops, timings, régimes, features, modèles de fill, tailles) — pas seulement les variantes gardées ;
  • IDEA-49 : tout résultat est comparé à des benchmarks honnêtes (cash, buy-and-hold, naïf, placebo) ;
  • IDEA-50 : ablation — une feature ajoutée doit améliorer le net OOS MARGINAL, sinon on la supprime ;
  • IDEA-51 : à performance comparable, la stratégie la PLUS SIMPLE gagne.

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import math
import statistics

#: étages obligatoires, dans l'ordre (IDEA-41). Aucun saut autorisé.
ETAGES = ("IDEA", "FAST_SANITY", "LARGE_SCREENING", "EXACT_REPLAY", "OOS_WALK_FORWARD",
          "HOLDOUT", "FORWARD_PAPER", "VERDICT")

#: dimensions à compter dans le multiple testing (IDEA-44).
DIMENSIONS = ("coins", "horizons", "seuils", "stops", "timings", "regimes", "features",
              "modeles_fill", "tailles")


def etage_suivant(etage: str) -> str | None:
    i = ETAGES.index(str(etage).upper()) if str(etage).upper() in ETAGES else None
    if i is None or i + 1 >= len(ETAGES):
        return None
    return ETAGES[i + 1]


def transition_valide(depuis: str, vers: str) -> dict:
    """IDEA-41 — on ne saute jamais un étage. Un passage direct LARGE_SCREENING -> HOLDOUT est refusé."""
    a, b = str(depuis).upper(), str(vers).upper()
    if a not in ETAGES or b not in ETAGES:
        return {"valide": False, "motif": "ETAGE_INCONNU"}
    ia, ib = ETAGES.index(a), ETAGES.index(b)
    if ib == ia + 1:
        return {"valide": True, "motif": "OK"}
    if ib <= ia:
        return {"valide": False, "motif": "RETOUR_EN_ARRIERE_OU_SUR_PLACE"}
    return {"valide": False, "motif": "SAUT_D_ETAGE:%s manquant" % ETAGES[ia + 1]}


def promouvable(resultat: dict) -> dict:
    """IDEA-42 — un résultat issu du FAST_SCREEN (approximatif) n'est JAMAIS promouvable : pas de champion,
    pas de pépite, pas de PnL validé tant qu'un EXACT_REPLAY ne l'a pas confirmé."""
    moteur = str(resultat.get("moteur", "")).upper()
    etage = str(resultat.get("etage", "")).upper()
    if moteur in ("FAST_SCREEN", "APPROX") or etage in ("FAST_SANITY", "LARGE_SCREENING"):
        return {"promouvable": False, "motif": "FAST_SCREEN_NON_PROMOUVABLE",
                "exige": "EXACT_REPLAY"}
    if moteur != "EXACT_REPLAY":
        return {"promouvable": False, "motif": "MOTEUR_NON_EXACT:%s" % (moteur or "inconnu")}
    return {"promouvable": True, "motif": "OK"}


def essais_effectifs(dimensions: dict) -> dict:
    """IDEA-44 — nombre d'essais EFFECTIF = produit des cardinalités explorées. C'est ce nombre (et non le
    nombre de variantes retenues) qui doit alimenter DSR/PBO : sinon la correction de multiplicité ment."""
    detail, n = {}, 1
    for d in DIMENSIONS:
        v = (dimensions or {}).get(d)
        card = len(v) if isinstance(v, (list, tuple, set)) else (int(v) if v else 0)
        detail[d] = card
        if card > 0:
            n *= card
    return {"n_essais_effectif": n, "detail": detail,
            "dimensions_explorees": [d for d, c in detail.items() if c > 1],
            "note": "a fournir a DSR/PBO — jamais le nombre de variantes RETENUES"}


def comparer_benchmarks(net_strategie_bps: float, benchmarks: dict) -> dict:
    """IDEA-49 — une stratégie n'est bonne que si elle bat TOUS les benchmarks honnêtes fournis
    (cash, buy-and-hold, naïf, placebo…). Un benchmark manquant rend la comparaison incomplète."""
    if not benchmarks:
        return {"bat_tous": False, "motif": "AUCUN_BENCHMARK_FOURNI", "complet": False}
    perdus, ecarts = [], {}
    for nom, val in benchmarks.items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            perdus.append(nom)
            continue
        ecarts[nom] = round(float(net_strategie_bps) - v, 4)
        if float(net_strategie_bps) <= v:
            perdus.append(nom)
    return {"bat_tous": not perdus, "battus_par": perdus, "ecarts_bps": ecarts,
            "complet": True,
            "motif": ("OK" if not perdus else "NE_BAT_PAS:%s" % ",".join(sorted(perdus)))}


def ablation(resultats_par_variante: dict, *, gain_min_bps: float = 0.0) -> dict:
    """IDEA-50 — A → A+B → A+B+C. Chaque feature ajoutée doit apporter un gain net OOS MARGINAL > seuil,
    sinon elle est marquée A_SUPPRIMER. On juge l'apport marginal, jamais le total."""
    ordre = sorted(resultats_par_variante or {}, key=lambda k: len(str(k).split("+")))
    lignes, precedent, precedent_nom = [], None, None
    for nom in ordre:
        try:
            net = float(resultats_par_variante[nom])
        except (TypeError, ValueError):
            continue
        gain = None if precedent is None else round(net - precedent, 4)
        garder = True if gain is None else gain > float(gain_min_bps)
        lignes.append({"variante": nom, "net_bps": round(net, 4), "gain_marginal_bps": gain,
                       "verdict": ("BASE" if gain is None else ("GARDER" if garder else "A_SUPPRIMER")),
                       "vs": precedent_nom})
        precedent, precedent_nom = net, nom
    return {"lignes": lignes,
            "features_a_supprimer": [l["variante"] for l in lignes if l["verdict"] == "A_SUPPRIMER"]}


def complexite(strategie: dict) -> int:
    """Compte les degrés de liberté d'une stratégie (paramètres + features + règles)."""
    return (len(strategie.get("params") or {}) + len(strategie.get("features") or [])
            + len(strategie.get("regles") or []))


def preferer_la_plus_simple(candidats: list, *, tolerance_bps: float = 1.0) -> dict:
    """IDEA-51 — à performance COMPARABLE (écart <= tolérance vs le meilleur), on garde la stratégie la
    moins complexe. La performance brute ne suffit jamais à justifier de la complexité."""
    valides = [c for c in (candidats or []) if isinstance(c.get("net_bps"), (int, float))]
    if not valides:
        return {"choisi": None, "motif": "AUCUN_CANDIDAT_MESURE"}
    meilleur = max(valides, key=lambda c: c["net_bps"])
    comparables = [c for c in valides if meilleur["net_bps"] - c["net_bps"] <= float(tolerance_bps)]
    choisi = min(comparables, key=lambda c: (complexite(c), -c["net_bps"]))
    return {"choisi": choisi.get("nom"), "net_bps": choisi["net_bps"],
            "complexite": complexite(choisi),
            "n_comparables": len(comparables),
            "motif": ("SIMPLICITE_A_PERFORMANCE_COMPARABLE" if choisi is not meilleur else "MEILLEUR_ET_SIMPLE")}


def sharpe_deflate_simple(sharpe: float, *, n_essais: int) -> dict:
    """IDEA-45 (complément honnête) — pénalisation grossière du Sharpe par le nombre d'essais EFFECTIF.
    Ce n'est PAS le DSR complet de Bailey/López de Prado (skew/kurtosis) : c'est un garde-fou rapide, et
    il est nommé comme tel pour ne pas se faire passer pour la vraie statistique."""
    try:
        s = float(sharpe)
        n = max(1, int(n_essais))
    except (TypeError, ValueError):
        return {"sharpe_penalise": None, "motif": "ENTREES_INVALIDES"}
    penalite = math.sqrt(2.0 * math.log(n)) if n > 1 else 0.0
    return {"sharpe_brut": round(s, 6), "n_essais": n, "penalite": round(penalite, 6),
            "sharpe_penalise": round(s - penalite, 6),
            "survit": (s - penalite) > 0,
            "avertissement": "approximation — le DSR complet reste la reference"}


__all__ = ["ETAGES", "DIMENSIONS", "etage_suivant", "transition_valide", "promouvable",
           "essais_effectifs", "comparer_benchmarks", "ablation", "complexite",
           "preferer_la_plus_simple", "sharpe_deflate_simple"]

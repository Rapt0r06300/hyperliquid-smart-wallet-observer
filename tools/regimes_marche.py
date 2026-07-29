"""RÉGIMES ET SIGNAL DECAY — temporels, microstructure, par coin, par horizon (IDEA-52 → 55).

Un edge qui n'existe que dans un régime précis n'est pas un edge : c'est une découverte à valider. Ce
module classe les épisodes en catégories **PRÉ-ENREGISTRÉES** (définies AVANT de voir le moindre résultat)
et compte chaque spécialisation comme un ESSAI supplémentaire à corriger en multiple testing.

  • IDEA-52 : régimes temporels (heure UTC, session Europe/US/Asie, weekday/weekend, début de minute/5 min/
    15 min/heure) — figés dans ce fichier, donc impossibles à retoucher après coup sans que ça se voie ;
  • IDEA-53 : régimes microstructure (vol, spread, profondeur, OI, funding, liquidations, directionnel) ;
  • IDEA-54 : le tuning par coin est autorisé mais COMPTE comme essai et doit être OOS ;
  • IDEA-55 : chaque horizon est une hypothèse séparée, avec sa propre correction de multiplicité.

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import time

#: catégories temporelles PRÉ-ENREGISTRÉES (IDEA-52). Ne pas modifier après avoir vu des résultats.
SESSIONS = {"ASIE": (0, 8), "EUROPE": (8, 14), "US": (14, 22), "NUIT": (22, 24)}
BORDS = ("DEBUT_MINUTE", "DEBUT_5MIN", "DEBUT_15MIN", "DEBUT_HEURE", "MILIEU")

#: seuils microstructure PRÉ-ENREGISTRÉS (IDEA-53), en unités explicites.
SEUILS_VOL_BPS = (5.0, 20.0)            # basse / moyenne / haute
SEUILS_SPREAD_BPS = (2.0, 8.0)          # serre / normal / large
SEUILS_PROFONDEUR_USD = (5_000.0, 50_000.0)   # mince / normale / epaisse


def _ts_ms(ts_ms):
    try:
        return float(ts_ms)
    except (TypeError, ValueError):
        return None


def regime_temporel(ts_ms) -> dict:
    """IDEA-52 — classe un timestamp en catégories temporelles pré-enregistrées (UTC)."""
    t = _ts_ms(ts_ms)
    if t is None:
        return {"mesurable": False, "motif": "TIMESTAMP_INVALIDE"}
    st = time.gmtime(t / 1000.0)
    heure, minute, seconde = st.tm_hour, st.tm_min, st.tm_sec
    session = next((n for n, (a, b) in SESSIONS.items() if a <= heure < b), "NUIT")
    if minute == 0 and seconde < 1:
        bord = "DEBUT_HEURE"
    elif minute % 15 == 0 and seconde < 1:
        bord = "DEBUT_15MIN"
    elif minute % 5 == 0 and seconde < 1:
        bord = "DEBUT_5MIN"
    elif seconde < 1:
        bord = "DEBUT_MINUTE"
    else:
        bord = "MILIEU"
    return {"mesurable": True, "heure_utc": heure, "session": session,
            "weekend": st.tm_wday >= 5, "jour_semaine": st.tm_wday, "bord": bord}


def regime_microstructure(*, vol_bps=None, spread_bps=None, profondeur_usd=None, funding_bps=None,
                          oi_usd=None, liquidations_usd=None, tendance=None) -> dict:
    """IDEA-53 — classe l'état du marché. Une mesure absente donne `INCONNU` (jamais une catégorie
    par défaut qui ferait passer un régime inconnu pour un régime calme)."""
    def _cat(v, seuils, noms):
        if v is None:
            return "INCONNU"
        try:
            x = float(v)
        except (TypeError, ValueError):
            return "INCONNU"
        return noms[0] if x < seuils[0] else (noms[1] if x < seuils[1] else noms[2])
    return {
        "vol": _cat(vol_bps, SEUILS_VOL_BPS, ("BASSE", "MOYENNE", "HAUTE")),
        "spread": _cat(spread_bps, SEUILS_SPREAD_BPS, ("SERRE", "NORMAL", "LARGE")),
        "profondeur": _cat(profondeur_usd, SEUILS_PROFONDEUR_USD, ("MINCE", "NORMALE", "EPAISSE")),
        "funding": ("INCONNU" if funding_bps is None else ("POSITIF" if float(funding_bps) > 0 else
                                                           ("NEGATIF" if float(funding_bps) < 0 else "NEUTRE"))),
        "oi": ("INCONNU" if oi_usd is None else "MESURE"),
        "liquidations": ("INCONNU" if liquidations_usd is None else
                         ("ACTIVES" if float(liquidations_usd) > 0 else "CALMES")),
        "tendance": (str(tendance).upper() if tendance else "INCONNU"),
    }


def cle_regime(temporel: dict, micro: dict) -> str:
    """Clé stable et lisible d'un régime combiné — sert de dimension d'analyse ET d'essai à compter."""
    return "%s|%s|vol=%s|spread=%s|prof=%s" % (
        temporel.get("session", "?"), temporel.get("bord", "?"),
        micro.get("vol", "?"), micro.get("spread", "?"), micro.get("profondeur", "?"))


def specialisations_comme_essais(*, coins=None, horizons=None, regimes=None) -> dict:
    """IDEA-54/55 — toute spécialisation (par coin, par horizon, par régime) est un ESSAI. Le total
    alimente la correction de multiplicité : se spécialiser n'est pas gratuit."""
    nc = len(coins or []) or 1
    nh = len(horizons or []) or 1
    nr = len(regimes or []) or 1
    return {"n_coins": nc, "n_horizons": nh, "n_regimes": nr,
            "n_essais_specialisation": nc * nh * nr,
            "exige_oos": True,
            "note": "chaque coin/horizon/regime est une HYPOTHESE separee, a valider en OOS"}


def verdict_par_regime(nets_par_regime: dict, *, min_n: int = 30) -> dict:
    """Résultat par régime, avec garde-fou d'échantillon : un régime sous `min_n` est NON_CONCLUANT et ne
    peut pas être présenté comme « le régime qui marche »."""
    lignes = []
    for regime, nets in (nets_par_regime or {}).items():
        xs = [float(x) for x in (nets or []) if isinstance(x, (int, float))]
        n = len(xs)
        med = (sorted(xs)[n // 2] if n else None)
        lignes.append({"regime": regime, "n": n,
                       "net_median_bps": (round(med, 4) if med is not None else None),
                       "concluant": n >= int(min_n)})
    concluants = [l for l in lignes if l["concluant"] and l["net_median_bps"] is not None]
    positifs = [l for l in concluants if l["net_median_bps"] > 0]
    return {"lignes": sorted(lignes, key=lambda l: -(l["net_median_bps"] or -1e9)),
            "n_concluants": len(concluants), "n_positifs": len(positifs),
            "regimes_positifs": [l["regime"] for l in positifs],
            "avertissement": "un edge present dans UN SEUL regime est une hypothese, pas un edge"}


__all__ = ["SESSIONS", "BORDS", "SEUILS_VOL_BPS", "SEUILS_SPREAD_BPS", "SEUILS_PROFONDEUR_USD",
           "regime_temporel", "regime_microstructure", "cle_regime", "specialisations_comme_essais",
           "verdict_par_regime"]

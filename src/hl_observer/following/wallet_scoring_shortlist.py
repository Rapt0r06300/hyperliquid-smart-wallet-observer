"""Scoring point-in-time des wallets et rotation des 10 slots `userFills` premium (pur, 0 réseau).

Deux principes, et tout le reste en découle.

**1. On ne classe jamais un wallet sur SON PnL.** Un leader peut gagner beaucoup et rester incopiable : si
son edge s'évapore avant que notre latence nous laisse entrer, ou s'il ne survit pas à nos frais, son PnL
brut ne nous appartient pas. Le score est donc le **markout net après NOTRE latence et NOS coûts** — la
seule quantité qui nous concerne.

**2. Les 10 slots WS sont une ressource rare, pas un classement.** Hyperliquid en donne 10 par IP. Ils
deviennent des slots de **confirmation temps réel** : `N_CORE` places aux wallets dont l'edge copiable est
mesuré, `N_CHALLENGERS` places à l'exploration. Sans exploration, on ne découvre plus rien ; sans hystérésis,
on passe son temps à permuter pour du bruit.

Deny-by-default : un wallet sans markouts exploitables n'a **pas** de score (`None`) — il n'est pas noté 0.
Un wallet non mesuré ne peut jamais prendre une place CORE ; il peut prendre une place CHALLENGER, qui existe
précisément pour le mesurer.
"""
from __future__ import annotations

import statistics
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "hypersmart.wallet_scoring_shortlist.v1"

#: Plafond Hyperliquid : 10 abonnements `userFills` par IP (cf. contrats API du bloc 13).
LIMITE_SLOTS_HL = 10
N_CORE = 8
N_CHALLENGERS = 2

#: Un challenger doit battre le plus faible des CORE de cette marge pour prendre sa place.
#: Sans elle, deux wallets équivalents permutent à chaque cycle et on ne mesure plus rien.
MARGE_HYSTERESIS_BPS = 2.0

#: Nombre minimal d'épisodes mesurables sous lequel aucun score n'est publié.
MIN_EPISODES = 20

#: Au-delà, l'edge du wallet vient d'un seul coup : ce n'est pas une compétence répétable.
CONCENTRATION_MAX = 0.35


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def score_point_in_time(episodes: Sequence[Mapping[str, Any]], *, as_of_ms: int,
                        cout_ar_bps: float, horizon_markout_ms: int,
                        min_episodes: int = MIN_EPISODES) -> dict[str, Any]:
    """Score d'un wallet à l'instant `as_of_ms`, **sans jamais regarder après**.

    `episodes` porte, par épisode, un dict `markouts_bps` {horizon_ms: bps}. L'horizon retenu doit être
    celui que NOTRE latence permet réellement d'atteindre.
    """
    passes = [e for e in episodes if (_f(e.get("ts_ms")) or 0) <= as_of_ms]
    nets: list[float] = []
    notionnels: list[float] = []
    sans_markout = 0
    for e in passes:
        markouts = e.get("markouts_bps")
        brut = _f((markouts or {}).get(horizon_markout_ms) if isinstance(markouts, Mapping)
                  else (markouts or {}).get(str(horizon_markout_ms)) if isinstance(markouts, Mapping) else None)
        if brut is None:
            sans_markout += 1
            continue
        nets.append(brut - float(cout_ar_bps))
        n = _f(e.get("notional_usd"))
        if n is not None and n > 0:
            notionnels.append(n)

    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "as_of_ms": int(as_of_ms),
        "horizon_markout_ms": int(horizon_markout_ms), "cout_ar_bps": float(cout_ar_bps),
        "n_episodes_vus": len(passes), "n_mesurables": len(nets), "n_sans_markout": sans_markout,
        "real_execution": False,
    }
    if len(nets) < int(min_episodes):
        return {**base, "score_copyable_bps": None, "eligible_core": False,
                "statut": "NON_MESURE",
                "raison": "%d episodes mesurables < %d requis" % (len(nets), int(min_episodes))}

    total = sum(nets)
    gains = [x for x in nets if x > 0]
    pertes = [x for x in nets if x < 0]
    concentration = (max(abs(x) for x in nets) / abs(total)) if abs(total) > 1e-12 else 1.0
    cumul = pic = dd = 0.0
    for x in nets:
        cumul += x
        pic = max(pic, cumul)
        dd = min(dd, cumul - pic)
    moyen = statistics.mean(nets)
    ecart = statistics.pstdev(nets)
    recence_ms = int(as_of_ms) - int(max((_f(e.get("ts_ms")) or 0) for e in passes))

    return {
        **base,
        "statut": "MESURE",
        "score_copyable_bps": round(moyen, 4),
        "net_total_bps": round(total, 4),
        "profit_factor": (round(sum(gains) / abs(sum(pertes)), 4) if pertes else None),
        "max_drawdown_bps": round(dd, 4),
        "hit_rate": round(len(gains) / len(nets), 4),
        "regularite": round(moyen / ecart, 4) if ecart > 1e-12 else None,
        "concentration": round(concentration, 4),
        "un_seul_gros_coup": bool(concentration > CONCENTRATION_MAX),
        "notional_median_usd": round(statistics.median(notionnels), 4) if notionnels else None,
        "recence_ms": recence_ms,
        # eligible CORE : edge copiable POSITIF apres nos couts ET repartition non concentree
        "eligible_core": bool(moyen > 0 and concentration <= CONCENTRATION_MAX),
    }


def classer(scores: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, float]]:
    """Wallets mesurés et éligibles, du meilleur au moins bon. Les non mesurés sont absents."""
    retenus = [(w, float(s["score_copyable_bps"])) for w, s in scores.items()
               if s.get("score_copyable_bps") is not None and s.get("eligible_core")]
    return sorted(retenus, key=lambda p: -p[1])


def shortlist(scores: Mapping[str, Mapping[str, Any]], *, slots_actuels: Sequence[str] = (),
              candidats_exploration: Iterable[str] = (), n_core: int = N_CORE,
              n_challengers: int = N_CHALLENGERS,
              marge_hysteresis_bps: float = MARGE_HYSTERESIS_BPS) -> dict[str, Any]:
    """Compose les 10 slots : `n_core` mesurés + `n_challengers` explorés, avec hystérésis.

    Un wallet déjà en place n'est délogé que si le prétendant le bat d'au moins `marge_hysteresis_bps` —
    sinon on permute pour du bruit et aucune mesure n'a le temps d'aboutir.
    """
    total = int(n_core) + int(n_challengers)
    if total > LIMITE_SLOTS_HL:
        return {"erreur": "SLOTS_AU_DELA_DE_LA_LIMITE_HL", "limite": LIMITE_SLOTS_HL,
                "demande": total, "core": [], "challengers": []}

    ordre = classer(scores)
    par_score = dict(ordre)
    actuels = [w for w in slots_actuels]
    actuels_core = [w for w in actuels if w in par_score][:int(n_core)]

    core = list(actuels_core)
    for wallet, valeur in ordre:
        if len(core) >= int(n_core):
            break
        if wallet not in core:
            core.append(wallet)

    # remplacement avec hystérésis : seuls les prétendants nettement meilleurs délogent
    remplacements: list[dict[str, Any]] = []
    if len(core) == int(n_core):
        pretendants = [(w, v) for w, v in ordre if w not in core]
        for wallet, valeur in pretendants:
            faible = min(core, key=lambda w: par_score.get(w, float("-inf")))
            valeur_faible = par_score.get(faible)
            if valeur_faible is None or valeur >= valeur_faible + float(marge_hysteresis_bps):
                core[core.index(faible)] = wallet
                remplacements.append({"sortant": faible, "entrant": wallet,
                                      "gain_bps": round(valeur - (valeur_faible or 0.0), 4)})
            else:
                break

    # challengers : exploration parmi les NON mesurés en priorité — c'est leur raison d'être
    deja = set(core)
    non_mesures = [w for w, s in scores.items()
                   if w not in deja and s.get("score_copyable_bps") is None]
    file = list(dict.fromkeys([*candidats_exploration, *non_mesures]))
    challengers = [w for w in file if w not in deja][:int(n_challengers)]

    return {
        "schema_version": SCHEMA_VERSION,
        "core": core, "challengers": challengers,
        "slots_utilises": len(core) + len(challengers), "limite_hl": LIMITE_SLOTS_HL,
        "remplacements": remplacements,
        "n_mesures_eligibles": len(ordre),
        "n_non_mesures": len([1 for s in scores.values() if s.get("score_copyable_bps") is None]),
        "marge_hysteresis_bps": float(marge_hysteresis_bps),
        "note": "les slots CORE exigent un edge copiable mesure ; les CHALLENGERS servent a mesurer",
        "real_execution": False,
    }


__all__ = ["SCHEMA_VERSION", "LIMITE_SLOTS_HL", "N_CORE", "N_CHALLENGERS", "MARGE_HYSTERESIS_BPS",
           "MIN_EPISODES", "CONCENTRATION_MAX", "score_point_in_time", "classer", "shortlist"]

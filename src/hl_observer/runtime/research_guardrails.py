"""Garde-fous de recherche canoniques IDEA-81 -> IDEA-91.

Ces protections existaient historiquement dans ``tools/garde_fous_recherche.py``.
Elles vivent maintenant dans ``src/hl_observer`` afin que le runtime officiel,
les replays et la CI puissent les invoquer sans dépendre du moteur legacy.

Aucun réseau, aucun ordre, aucune signature, aucune clé. Calcul pur / paper-only.
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.runtime_research_guardrails.v1"

# Limites de garde internes. Elles servent de plafond fail-closed au runtime ; toute
# évolution documentaire doit passer par un changement explicite + tests, jamais par
# une hausse silencieuse au milieu d'un run.
LIMITES_HL = {
    "ws_connexions_par_ip": 10,
    "ws_nouvelles_par_minute": 30,
    "subscriptions": 1000,
    "users_uniques_subscriptions": 10,
    "messages_par_minute": 2000,
    "l2_niveaux": 20,
}

METRIQUES_LIVE_VS_BACKTEST = (
    "n_signaux",
    "fill_rate",
    "pnl",
    "roi",
    "drawdown",
    "couts",
    "slippage",
    "profit_factor",
    "win_rate",
    "markouts",
)


def esperance_entree(
    *,
    qualite_prix_bps: float,
    probabilite_succes: float,
    gain_attendu_bps: float,
    couts_bps: float,
) -> dict[str, Any]:
    """IDEA-81 — prix x probabilité, jamais le filtre naïf « meilleur prix = mieux »."""
    try:
        p = float(probabilite_succes)
        g = float(gain_attendu_bps)
        c = float(couts_bps)
        q = float(qualite_prix_bps)
    except (TypeError, ValueError):
        return {"mesurable": False, "motif": "ENTREES_INVALIDES", "real_execution": False}
    if not 0.0 <= p <= 1.0:
        return {"mesurable": False, "motif": "PROBABILITE_HORS_BORNES", "real_execution": False}
    esp = p * g - (1.0 - p) * abs(g) - c + q
    return {
        "mesurable": True,
        "esperance_bps": round(esp, 4),
        "rentable": esp > 0,
        "note": "un meilleur prix ne compense pas une probabilite effondree",
        "real_execution": False,
    }


def comparer_styles(nets_par_style: Mapping[str, Sequence[float]], *, min_n: int = 30) -> dict[str, Any]:
    """IDEA-82 — compare les styles sur mêmes données/coûts/règles."""
    lignes: list[dict[str, Any]] = []
    for style, nets in (nets_par_style or {}).items():
        xs = [float(x) for x in (nets or ()) if isinstance(x, (int, float)) and not isinstance(x, bool)]
        lignes.append(
            {
                "style": str(style),
                "n": len(xs),
                "net_median_bps": round(statistics.median(xs), 4) if xs else None,
                "concluant": len(xs) >= int(min_n),
            }
        )
    concluants = [row for row in lignes if row["concluant"] and row["net_median_bps"] is not None]
    gagnant = max(concluants, key=lambda row: float(row["net_median_bps"]))["style"] if concluants else None
    return {
        "lignes": sorted(lignes, key=lambda row: -(row["net_median_bps"] if row["net_median_bps"] is not None else -1e9)),
        "gagnant": gagnant,
        "exige": "memes donnees, memes couts, memes regles",
        "real_execution": False,
    }


def adverse_selection_par_stade(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """IDEA-83 — mesure la toxicité selon le stade d'exécution du métaordre."""
    paquets: dict[str, list[float]] = {}
    for obs in observations or ():
        stade = obs.get("stade_execution")
        markout = obs.get("markout_bps")
        if not isinstance(stade, (int, float)) or isinstance(stade, bool):
            continue
        if not isinstance(markout, (int, float)) or isinstance(markout, bool):
            continue
        tranche = "0-33%" if float(stade) < 0.33 else ("33-66%" if float(stade) < 0.66 else "66-100%")
        paquets.setdefault(tranche, []).append(float(markout))
    lignes = [
        {"tranche": tranche, "n": len(values), "markout_median_bps": round(statistics.median(values), 4)}
        for tranche, values in sorted(paquets.items())
    ]
    return {
        "lignes": lignes,
        "tranche_la_plus_toxique": min(lignes, key=lambda row: row["markout_median_bps"])["tranche"] if lignes else None,
        "real_execution": False,
    }


def horloges_lead_lag() -> dict[str, Any]:
    """IDEA-84 — horloges de lead-lag déclarées avant lecture du holdout."""
    return {
        "horloges": ("DEBUT_SECONDE", "DEBUT_MINUTE", "DEBUT_5MIN", "DEBUT_15MIN"),
        "pre_enregistrees": True,
        "exige_oos": True,
        "n_essais": 4,
        "real_execution": False,
    }


def bibliotheque_erreurs(journal_resume: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """IDEA-85 — stress issu en priorité des incidents réellement observés."""
    catalogue = (
        "reconnect",
        "delayed_feed",
        "missing_l2",
        "stale_bbo",
        "partial_fill",
        "latency_spike",
        "gap",
        "bad_snapshot",
    )
    observes = sorted(str(x) for x in (journal_resume or {}).get("par_type", {}).keys())
    return {
        "scenarios_catalogue": catalogue,
        "n_catalogue": len(catalogue),
        "incidents_reellement_observes": observes,
        "source": "journal_operationnel" if observes else "catalogue_par_defaut",
        "exige_avant_promotion_forte": True,
        "real_execution": False,
    }


def verifier_plan_websockets(
    n_connexions: int,
    *,
    nouvelles_par_minute: int = 0,
    subscriptions: int = 0,
    users_uniques: int = 0,
) -> dict[str, Any]:
    """IDEA-86 — refuse toute architecture WS dépassant les plafonds internes."""
    violations: list[str] = []
    if int(n_connexions) > LIMITES_HL["ws_connexions_par_ip"]:
        violations.append(f"CONNEXIONS>{LIMITES_HL['ws_connexions_par_ip']}")
    if int(nouvelles_par_minute) > LIMITES_HL["ws_nouvelles_par_minute"]:
        violations.append(f"NOUVELLES_PAR_MINUTE>{LIMITES_HL['ws_nouvelles_par_minute']}")
    if int(subscriptions) > LIMITES_HL["subscriptions"]:
        violations.append(f"SUBSCRIPTIONS>{LIMITES_HL['subscriptions']}")
    if int(users_uniques) > LIMITES_HL["users_uniques_subscriptions"]:
        violations.append(f"USERS_UNIQUES>{LIMITES_HL['users_uniques_subscriptions']}")
    return {
        "conforme": not violations,
        "violations": violations,
        "limites": dict(LIMITES_HL),
        "recommandation": "peu de connexions robustes + multiplexage + quality scoring",
        "real_execution": False,
    }


def convertir_seuil_polymarket(seuil_cents: float) -> dict[str, Any]:
    """IDEA-87 — refuse de transposer un seuil en cents à un perp Hyperliquid."""
    return {
        "transposable": False,
        "seuil_cents": seuil_cents,
        "motif": "un marche de prediction en cents ne se transpose pas a un perp",
        "unites_correctes": ("bps", "volatilite", "spread", "profondeur", "age_ms"),
        "real_execution": False,
    }


def verifier_absence_wallet(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """IDEA-88 — aucun wallet/clé/signature dans la configuration de recherche."""
    interdits = (
        "private_key",
        "mnemonic",
        "seed",
        "wallet_address",
        "signer",
        "api_secret",
        "secret_key",
    )
    presents = [key for key in interdits if (config or {}).get(key)]
    return {
        "conforme": not presents,
        "champs_interdits_presents": presents,
        "motif": "OK — aucun wallet, aucune cle, aucune signature" if not presents else "CONFIG INTERDITE: " + ",".join(presents),
        "real_execution": False,
    }


def poids_preuve(source: str, *, chiffre: Any = None) -> dict[str, Any]:
    """IDEA-89 — marketing/externe = inspiration ; mesure interne = preuve."""
    normalise = str(source).upper()
    interne = normalise in {"MESURE_INTERNE", "OOS_INTERNE", "FORWARD_PAPER"}
    return {
        "source": normalise,
        "valeur_de_preuve": interne,
        "role": "PREUVE" if interne else "INSPIRATION",
        "chiffre": chiffre,
        "motif": "mesure interne reproductible" if interne else "chiffre externe/marketing — ne valide RIEN chez nous",
        "real_execution": False,
    }


def hypothese_falsifiable(
    nom: str,
    *,
    prediction: str,
    critere_kill: str,
    pre_enregistre: bool = False,
) -> dict[str, Any]:
    """IDEA-90 — une hypothèse n'est validable que si elle est falsifiable et pré-enregistrée."""
    manque = [name for name, value in (("prediction", prediction), ("critere_kill", critere_kill)) if not value]
    valide = not manque and bool(pre_enregistre)
    return {
        "hypothese": nom,
        "prediction": prediction,
        "critere_kill": critere_kill,
        "pre_enregistre": bool(pre_enregistre),
        "valide": valide,
        "motif": "OK" if valide else "NON_FALSIFIABLE: " + (",".join(manque) or "non pre-enregistree"),
        "real_execution": False,
    }


def comparer_live_backtest(
    live: Mapping[str, Any],
    backtest: Mapping[str, Any],
    *,
    tolerance_relative: float = 0.10,
) -> dict[str, Any]:
    """IDEA-91 — compare chaque métrique ; une valeur absente n'est jamais ignorée."""
    lignes: list[dict[str, Any]] = []
    manquantes: list[str] = []
    for metric in METRIQUES_LIVE_VS_BACKTEST:
        a = (live or {}).get(metric)
        b = (backtest or {}).get(metric)
        if not isinstance(a, (int, float)) or isinstance(a, bool) or not isinstance(b, (int, float)) or isinstance(b, bool):
            manquantes.append(metric)
            continue
        base = max(abs(float(b)), 1e-9)
        ecart = abs(float(a) - float(b)) / base
        lignes.append(
            {
                "metrique": metric,
                "live": float(a),
                "backtest": float(b),
                "ecart_relatif": round(ecart, 6),
                "diverge": ecart > float(tolerance_relative),
            }
        )
    divergentes = [row["metrique"] for row in lignes if row["diverge"]]
    return {
        "lignes": lignes,
        "metriques_divergentes": divergentes,
        "metriques_manquantes": manquantes,
        "coherent": not divergentes and not manquantes,
        "motif": "comparaison metrique par metrique — jamais un pourcentage global unique",
        "real_execution": False,
    }


__all__ = [
    "SCHEMA_VERSION",
    "LIMITES_HL",
    "METRIQUES_LIVE_VS_BACKTEST",
    "esperance_entree",
    "comparer_styles",
    "adverse_selection_par_stade",
    "horloges_lead_lag",
    "bibliotheque_erreurs",
    "verifier_plan_websockets",
    "convertir_seuil_polymarket",
    "verifier_absence_wallet",
    "poids_preuve",
    "hypothese_falsifiable",
    "comparer_live_backtest",
]

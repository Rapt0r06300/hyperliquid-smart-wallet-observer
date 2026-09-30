"""P2.2 — ventilation des observations INDÉPENDANTES (pas seulement « nombre d'épisodes »).

Un N gonflé fait mentir tout test de significativité : 200 fills d'un même métaordre ne sont pas 200
observations, mais UNE. Ce module réutilise l'AUTORITÉ de groupement déjà livrée
(`following.scoring_robuste.cle_grappe` : `metaorder_id`/`twap_id`/`burst_id`, sinon wallet×coin×jour) —
**aucune seconde définition** — et publie la ventilation exigée : `n_raw_fills`, `n_metaorders`,
`n_bursts`, `n_wallet_coin_days`, `n_episodes`, `n_independent` (= nombre de grappes = votes
indépendants), plus la borne basse de confiance des votes (réutilise `borne_basse_confiance`).

`n_independent` est le nombre à utiliser partout où l'on juge la significativité. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.following.scoring_robuste import (
    agreger_en_grappes,
    borne_basse_confiance,
    cle_grappe,
)

SCHEMA_VERSION = "hypersmart.independent_breakdown.v1"


def _identite_episode(e: Mapping[str, Any]) -> str | None:
    for cle in ("episode_id", "position_id"):
        v = e.get(cle)
        if v not in (None, "", 0, "0"):
            return f"{cle}:{v}"
    return None


def ventilation_independance(
    episodes: Sequence[Mapping[str, Any]], *, cle_valeur: str = "net_bps"
) -> dict[str, Any]:
    """Publie la ventilation complète du N indépendant à partir des épisodes/fills.

    Chaque enregistrement est rattaché à UNE grappe via `cle_grappe`. `n_independent` = nombre de
    grappes distinctes (metaorder/burst/wallet-coin-jour confondus). Les votes (moyenne intra-grappe)
    alimentent la borne basse de confiance."""
    eps = list(episodes)
    par_prefixe: dict[str, set[str]] = {"metaorder": set(), "burst": set(), "wcj": set()}
    episodes_ids: set[str] = set()
    for e in eps:
        k = cle_grappe(e)
        prefixe = k.split(":", 1)[0]
        if prefixe in ("metaorder_id", "twap_id"):
            par_prefixe["metaorder"].add(k)
        elif prefixe == "burst_id":
            par_prefixe["burst"].add(k)
        else:
            par_prefixe["wcj"].add(k)
        ident = _identite_episode(e)
        if ident is not None:
            episodes_ids.add(ident)

    agr = agreger_en_grappes(eps, cle_valeur=cle_valeur)
    n_independent = len(par_prefixe["metaorder"]) + len(par_prefixe["burst"]) + len(par_prefixe["wcj"])
    votes = agr.get("votes_bps") or []
    lcb = borne_basse_confiance(votes) if votes else None

    return {
        "schema_version": SCHEMA_VERSION,
        "n_raw_fills": len(eps),
        "n_metaorders": len(par_prefixe["metaorder"]),
        "n_bursts": len(par_prefixe["burst"]),
        "n_wallet_coin_days": len(par_prefixe["wcj"]),
        "n_episodes": (len(episodes_ids) if episodes_ids else None),   # None si aucune identité d'épisode
        "n_independent": n_independent,
        "facteur_replication": agr.get("facteur_replication"),
        "n_votes_avec_valeur": agr.get("n_votes_independants"),
        "lower_confidence_bound_bps": lcb,
        "real_execution": False,
    }


__all__ = ["SCHEMA_VERSION", "ventilation_independance"]

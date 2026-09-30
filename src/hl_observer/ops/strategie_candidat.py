"""LA STRATÉGIE EFFECTIVE D'UN CANDIDAT — une seule vérité pour la mesure ET le crible (22/07).

LE DÉFAUT MESURÉ
----------------
Le rapport qualité criait « **9 %** des candidats portent une `strategie` » et classait ça en
« DÉFAUTS À CORRIGER ». Mesure réelle sur 200 000 candidats consolidés :

    AVEC strategie : 22,4 %   (copy 43 304 · arbitrage 759 · carry 705)
    SANS strategie : 77,6 %   ← MAIS tous portent `leader_wallet` / `leader_score` /
                                 `consensus_wallets` : ce SONT des candidats copy, écrits
                                 avant que l'écrivain ne pose l'étiquette (correctif du 21/07).

Donc l'étiquette brute ment dans les deux sens : elle dit « 9 % » (alarme) alors que
**~100 % sont classables** — soit par leur label, soit par leurs champs. Et le crible mappait
les « ? » en copy **à l'aveugle** : un candidat carry ou arbitrage qui perdrait son label
serait compté copy par accident.

CE QUE CE MODULE FAIT
---------------------
Une fonction `strategie_effective(candidat)`, utilisée par la métrique qualité ET par le
crible, pour qu'ils s'accordent :

  1. label explicite présent et connu  -> on le prend (normalisé via les alias) ;
  2. sinon, champs de COPY (leader/consensus)  -> `copy` ;
  3. sinon, champs d'ARBITRAGE (écart de prix) -> `arbitrage` ;
  4. sinon, champs de CARRY (funding + base)   -> `carry` ;
  5. sinon seulement  -> `?` : VRAIMENT ambigu, et c'est CE chiffre qui mérite l'alarme.

On n'invente jamais une stratégie : on la LIT dans ce que le candidat porte déjà. Un candidat
qui ne porte aucun marqueur reste `?` — le défaut honnête, pas un rangement de confort.

PAPER only : classer un candidat n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any

STRATEGIES = ("carry", "copy", "arbitrage")
INCONNU = "?"

#: normalisation des libellés vus dans les données (le firehose et l'historique varient).
_ALIAS = {
    "copy": "copy", "carry": "carry",
    "arbitrage": "arbitrage", "funding_arb": "arbitrage", "triangular": "arbitrage",
}
#: champs distinctifs de chaque stratégie (mesurés sur les vrais candidats).
_CHAMPS_COPY = ("leader_wallet", "leader_score", "consensus_wallets",
                "leader_expected_edge_bps", "leader_consistency_factor")
_CHAMPS_ARB = ("ecart_prix_bps", "venue_haute", "hl_px", "bin_px")
_CHAMPS_CARRY = ("funding_bps_h", "base_bps", "base_mid_bps")


def _a_un_champ(candidat: dict[str, Any], champs) -> bool:
    return any(candidat.get(c) not in (None, "") for c in champs)


def strategie_effective(candidat: Any) -> str:
    """La stratégie d'un candidat : son label si connu, sinon INFÉRÉE de ses champs, sinon `?`.

    Ne devine JAMAIS au-delà de ce que le candidat porte : sans label ET sans marqueur, c'est
    `?` — le vrai défaut, celui qu'il faut mesurer et non masquer.
    """
    if not isinstance(candidat, dict):
        return INCONNU
    brut = str(candidat.get("strategie") or "").strip().lower()
    if brut and brut != INCONNU and brut in _ALIAS:
        return _ALIAS[brut]
    # label absent ou inconnu -> on infère des champs, dans l'ordre du plus distinctif.
    if _a_un_champ(candidat, _CHAMPS_COPY):
        return "copy"
    if _a_un_champ(candidat, _CHAMPS_ARB):
        return "arbitrage"
    if _a_un_champ(candidat, _CHAMPS_CARRY):
        return "carry"
    return INCONNU


def resume_etiquetage(candidats: Any) -> dict[str, Any]:
    """La VRAIE santé de l'étiquetage : classés par label, classés par inférence, ambigus.

    C'est ce résumé qui doit alimenter l'alarme — pas le taux de label brut, qui prend un
    historique parfaitement classable pour un défaut.
    """
    par_label = 0
    par_inference = 0
    ambigus = 0
    par_strat: dict[str, int] = {}
    total = 0
    for c in (candidats or ()):
        if not isinstance(c, dict):
            continue
        total += 1
        brut = str(c.get("strategie") or "").strip().lower()
        eff = strategie_effective(c)
        if brut and brut in _ALIAS:
            par_label += 1
        elif eff != INCONNU:
            par_inference += 1
        else:
            ambigus += 1
        par_strat[eff] = par_strat.get(eff, 0) + 1
    if not total:
        return {"total": 0, "classes_pct": 100.0, "ambigus": 0, "par_strategie": {},
                "label_brut_pct": 100.0}
    classes = par_label + par_inference
    return {
        "total": total,
        "label_brut_pct": round(100.0 * par_label / total, 2),
        "classes_pct": round(100.0 * classes / total, 2),   # label OU inférence : la vérité
        "par_inference": par_inference,
        "ambigus": ambigus,
        "ambigus_pct": round(100.0 * ambigus / total, 2),
        "par_strategie": dict(sorted(par_strat.items(), key=lambda kv: -kv[1])),
    }


__all__ = ["STRATEGIES", "INCONNU", "strategie_effective", "resume_etiquetage"]

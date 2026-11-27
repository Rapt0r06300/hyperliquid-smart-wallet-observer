"""Portage couvert sur funding : encaisser le funding d'Hyperliquid en restant neutre sur le prix (26/11/2026).

Hypothese ``funding_hedged_carry_majors`` (Florent, 26/11 : « si tu penses qu'on peut se faire un revenu dessus oui » --
piste rouverte en recherche PAPER, aucun ordre, HORS famille CopyVault : jamais promue par le plan CopyVault).

⚠ MESURE IN-SAMPLE, EXPLORATOIRE (correctif du 26/11 au soir). La regle N'A PAS ete figee avant de voir les donnees :
K = 5, la liste des 20 coins et les MEMES 36 mois avaient deja ete regardes dans un premier calcul (script de session
« carry_premier_chiffre »), et la liste est celle des gros coins d'AUJOURD'HUI (biais du survivant possible). Le
verdict historique ne vaut donc que comme piste ; la SEULE confirmation recevable est un suivi PAPER sur des mois
posterieurs au 26/11/2026, regle inchangee. La regle, telle qu'elle est maintenant gelee :

  * chaque periode de 30 jours, choisir les K = 5 coins de l'UNIVERS COUVRABLE dont le funding horaire moyen des 30 jours
    PRECEDENTS est le plus fort et positif (heures couvertes >= 90 %) ; tenir un short perp Hyperliquid couvert par un
    long au comptant ailleurs ; encaisser le funding des 30 jours SUIVANTS. Aucune donnee posterieure a l'entree n'est lue ;
  * cout : 18,5 bps par coin qui ENTRE ou qui SORT (perp taker 4,5 + comptant taker 10 + 2 x 2 bps de glissement) ;
  * capital = notionnel x (1 + marge), marge du short = 50 % (levier 2 : de quoi tenir une flambee de +50 %) ;
  * statut : REJECTED si la borne HAUTE de l'IC95 (blocs de 3 mois) du net mensuel est < 0 ; PROMISING si la borne BASSE
    est > 0 ET la moyenne du dernier tiers des mois (validation) est > 0 ; sinon MORE_DATA. Moins de 12 mois : MORE_DATA.
    PROVEN n'est JAMAIS rendu par l'historique seul : il faut des mois NOUVEAUX suivis en papier.

Hypotheses optimistes DECLAREES (le rapport les repete) : couverture parfaite (ecart perp / comptant ignore), comptant
disponible pour chaque coin de l'univers, aucune liquidation. Le 26/11, la meme regle sur TOUS les coins choisissait
surtout des marches impossibles a couvrir (xyz:NATGAS, para:AVGO, memecoins) : d'ou l'univers declare ci-dessous.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

SCHEMA = "hypersmart.portage_couvert.v1"
HYPOTHESE = "funding_hedged_carry_majors"
EVIDENCE_TIER = "LOCAL_PUBLISHED_FUNDING_HISTORY_EXPLORATORY"
HEURE_MS, JOUR_MS = 3_600_000, 86_400_000

#: Univers DECLARE : gros coins dont un marche au comptant profond existe ailleurs (couverture possible). A remplacer par
#: une liste OBSERVEE (cotations au comptant certifiees au coffre) quand elle existera.
UNIVERS_COUVRABLE = frozenset({
    "BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LINK", "SUI",
    "HYPE", "LTC", "BCH", "DOT", "TRX", "TON", "NEAR", "APT", "ARB", "OP",
})


@dataclass(frozen=True)
class PortageConfig:
    k: int = 5
    fenetre_jours: int = 30
    couverture_min: float = 0.9
    frais_rotation_bps: float = 18.5
    marge: float = 0.5
    bloc_mois: int = 3
    tirages: int = 2000
    graine: int = 7
    mois_min: int = 12
    part_validation: float = 1.0 / 3.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def funding_journalier(observations: Iterable[tuple[Any, Any, Any]]) -> dict[str, Any]:
    """Somme des taux horaires et nombre d'heures, par coin et par jour UTC. Une heure n'est comptee qu'une fois."""
    vus: set[tuple[str, int]] = set()
    acc: dict[str, dict[int, list[float]]] = {}
    for coin, ts, taux in observations:
        if not isinstance(coin, str) or not coin or isinstance(ts, bool) or not isinstance(ts, (int, float)):
            continue
        try:
            f = float(taux)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(f) or ts <= 0:
            continue
        cle = (coin, int(ts) // HEURE_MS)
        if cle in vus:
            continue
        vus.add(cle)
        jour = acc.setdefault(coin, {}).setdefault(int(ts) // JOUR_MS, [0.0, 0.0])
        jour[0] += f
        jour[1] += 1.0
    if not acc:
        return {"jour0": None, "coins": [], "somme": np.zeros((0, 0)), "heures": np.zeros((0, 0))}
    jour0 = min(min(d) for d in acc.values())
    n = max(max(d) for d in acc.values()) - jour0 + 1
    coins = sorted(acc)
    somme, heures = np.zeros((len(coins), n)), np.zeros((len(coins), n))
    for i, coin in enumerate(coins):
        for jour, (s, h) in acc[coin].items():
            somme[i, jour - jour0], heures[i, jour - jour0] = s, h
    return {"jour0": jour0, "coins": coins, "somme": somme, "heures": heures}


def simuler_portage(fj: dict[str, Any], config: PortageConfig, *, univers: frozenset[str] = UNIVERS_COUVRABLE,
                    k: int | None = None) -> list[dict[str, Any]]:
    """Une ligne par periode : coins choisis sur le PASSE, funding encaisse sur la periode SUIVANTE, net de frais."""
    k = config.k if k is None else int(k)
    coins, somme, heures = fj["coins"], fj["somme"], fj["heures"]
    n = somme.shape[1] if somme.size else 0
    f = int(config.fenetre_jours)
    eligibles = [i for i, c in enumerate(coins) if c in univers]
    tenus: set[int] = set()
    periodes: list[dict[str, Any]] = []
    for debut in range(f, n - f + 1, f):
        score = {}
        for i in eligibles:
            h = float(heures[i, debut - f:debut].sum())
            if h >= config.couverture_min * f * 24:
                score[i] = float(somme[i, debut - f:debut].sum()) / h
        ordre = sorted(score.items(), key=lambda kv: (-kv[1], coins[kv[0]]))[:k]
        choix = {i for i, s in ordre if s > 0}
        entrees, sorties = choix - tenus, tenus - choix
        frais = config.frais_rotation_bps * (len(entrees) / max(len(choix), 1) + len(sorties) / max(len(tenus), 1))
        funding = (sum(float(somme[i, debut:debut + f].sum()) for i in choix) / len(choix) * 1e4) if choix else 0.0
        periodes.append({"jour_debut": int((fj["jour0"] or 0) + debut), "coins": sorted(coins[i] for i in choix),
                         "funding_bps": funding, "frais_bps": frais, "net_bps": funding - frais})
        tenus = choix
    return periodes


def intervalle_par_blocs(valeurs: list[float], *, bloc: int, tirages: int, graine: int) -> tuple[float, float]:
    """IC95 de la moyenne par bootstrap a blocs mobiles (les regimes de funding durent plusieurs mois)."""
    x = np.asarray(valeurs, dtype=float)
    n = len(x)
    if n < 2:
        return (float("nan"), float("nan"))
    b = max(1, min(int(bloc), n))
    rng = np.random.default_rng(int(graine))
    nb = math.ceil(n / b)
    moyennes = np.empty(int(tirages))
    for t in range(int(tirages)):
        debuts = rng.integers(0, n - b + 1, nb)
        moyennes[t] = np.concatenate([x[d:d + b] for d in debuts])[:n].mean()
    return (float(np.percentile(moyennes, 2.5)), float(np.percentile(moyennes, 97.5)))


def _resume(periodes: list[dict[str, Any]], config: PortageConfig) -> dict[str, Any]:
    nets = [p["net_bps"] for p in periodes]
    if not nets:
        return {"mois": 0}
    capital = 1.0 + config.marge
    moyenne = float(np.mean(nets))
    bas, haut = intervalle_par_blocs(nets, bloc=config.bloc_mois, tirages=config.tirages, graine=config.graine)
    coupe = int(round(len(nets) * (1.0 - config.part_validation)))
    validation = nets[coupe:] or nets
    f = config.fenetre_jours
    return {
        "mois": len(nets), "net_moyen_bps_mois_notionnel": round(moyenne, 2),
        "intervalle_bps_mois_notionnel": [round(bas, 2), round(haut, 2)],
        "net_par_an_pct_du_capital": round(moyenne * 365 / f / 100 / capital, 2),
        "effet_bps_jour_capital": round(moyenne / f / capital, 4),
        "intervalle_bps_jour_capital": [round(bas / f / capital, 4), round(haut / f / capital, 4)],
        "validation_mois": len(validation), "validation_moyenne_bps_mois": round(float(np.mean(validation)), 2),
        "mois_negatifs": int(sum(1 for x in nets if x < 0)), "pire_mois_bps": round(min(nets), 2),
        "six_derniers_mois_bps": [round(x, 1) for x in nets[-6:]],
        "jours": len(nets) * f, "jours_requis": config.mois_min * f,
        "dernier_choix": periodes[-1]["coins"],
    }


def etudier(observations: Iterable[tuple[Any, Any, Any]], config: PortageConfig | None = None) -> dict[str, Any]:
    config = config or PortageConfig()
    fj = funding_journalier(observations)
    periodes = simuler_portage(fj, config)
    primary = _resume(periodes, config)
    n = primary["mois"]
    if n < config.mois_min:
        statut, raison = "MORE_DATA", f"{n} mois mesures ; il en faut au moins {config.mois_min}"
    else:
        bas, haut = primary["intervalle_bps_mois_notionnel"]
        if haut < 0:
            statut = "REJECTED"
            raison = f"le portage PERD : IC95 du net [{bas:+.1f} ; {haut:+.1f}] bps/mois, entierement sous zero"
        elif bas > 0 and primary["validation_moyenne_bps_mois"] > 0:
            statut = "PROMISING"
            raison = (f"net {primary['net_moyen_bps_mois_notionnel']:+.1f} bps/mois du notionnel, IC95 [{bas:+.1f} ; "
                      f"{haut:+.1f}] > 0, validation (dernier tiers) {primary['validation_moyenne_bps_mois']:+.1f} > 0 ; "
                      f"~{primary['net_par_an_pct_du_capital']:+.1f} %/an du capital -- a CONFIRMER sur des mois NOUVEAUX")
        else:
            statut = "MORE_DATA"
            raison = (f"net {primary['net_moyen_bps_mois_notionnel']:+.1f} bps/mois, IC95 [{bas:+.1f} ; {haut:+.1f}] : "
                      "ne tranche pas")
    par_k = {str(kk): _resume(simuler_portage(fj, config, k=kk), config) for kk in (3, 10)}
    vus_couvrables = sorted(c for c in fj["coins"] if c in UNIVERS_COUVRABLE)
    return {
        "schema": SCHEMA, "hypotheses_tested": [HYPOTHESE], "config": config.as_dict(),
        "inputs": {"coins": len(fj["coins"]), "coins_couvrables_vus": len(vus_couvrables),
                   "jours": int(fj["somme"].shape[1]) if fj["somme"].size else 0,
                   "premier_jour_utc": fj["jour0"],
                   "heures_de_funding": int(fj["heures"].sum()) if fj["heures"].size else 0},
        "primary": primary, "par_k_informatif": par_k, "periodes": periodes,
        "verdicts": [{"hypothesis": HYPOTHESE, "status": statut, "reason": raison}],
        "hypotheses_declarees": [
            "couverture parfaite : l'ecart perp / comptant est ignore",
            "comptant disponible pour chaque coin de l'univers declare",
            "aucune liquidation du short (marge de 50 %)",
        ],
    }


__all__ = ["EVIDENCE_TIER", "HYPOTHESE", "PortageConfig", "SCHEMA", "UNIVERS_COUVRABLE", "etudier",
           "funding_journalier", "intervalle_par_blocs", "simuler_portage"]

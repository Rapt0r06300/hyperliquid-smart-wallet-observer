"""Réplication PAPER du portefeuille d'un leader sous les contraintes RÉELLES d'un petit compte.

La copie des fills est réfutée ; la seule formulation encore ouverte est de tenir, lentement, le
portefeuille observé d'un leader. Les études précédentes la mesuraient en points de base par unité
d'exposition. Ce simulateur répond à la question concrète : qu'aurait fait un compte PAPER de
350 USD, avec ce qu'une plateforme impose réellement ?

* ordre minimal de la plateforme (10 USD) : une ligne du portefeuille du leader qui pèse moins ne
  peut PAS être reproduite — c'est une erreur de suivi, pas un détail ;
* frais taker et demi-écart payés à chaque ordre, depuis la source unique des frais ;
* funding payé ou reçu sur la position tenue, quand il est observé (jamais supposé nul) ;
* délai entre l'observation du portefeuille et l'ordre ; portefeuille trop ancien = cible inconnue,
  on ne touche à rien ; prix périmé = valorisation inconnue, la journée n'est pas comptée ;
* exposition brute plafonnée au capital (aucun levier) ; bande de non-transaction pour ne pas
  payer des frais sur du bruit.

Le compte est un compte de marge : les liquidités portent le capital et tout le PnL réalisé, une
position ne vaut que son PnL latent. La fonction est pure et déterministe. Elle sert au
laboratoire ; le moteur PAPER devra appeler la MÊME fonction le jour où une politique de
réplication sera gelée et certifiée (parité par construction). ``decomposer_les_pertes`` rejoue la
trajectoire en ajoutant les frictions une à une : on sait ce que coûtent, séparément, le délai,
les frais, le funding et l'ordre minimal.

Résultat EXPLORATOIRE : aucune rentabilité n'est prouvée par une simulation.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import numpy as np

from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD
from hl_observer.fees.hyperliquid_fees import MIN_ORDER_VALUE_USD, TAKER_PERP_BPS

DAY_MS = 86_400_000
H_REPLICATION_350 = "copy_vault_slow_replication_350usd"
Portefeuille = Sequence[tuple[int, float | None, Mapping[str, float]]]


@dataclass(frozen=True, slots=True)
class ReplicationConfig:
    capital_usd: float = PAPER_EQUITY_USD
    leverage_cap: float = 1.0               # exposition brute <= capital : aucun levier
    rebalance_ms: int = 3_600_000           # un réalignement par heure
    reaction_ms: int = 60_000               # délai entre l'observation du portefeuille et l'ordre
    max_snapshot_age_ms: int = 900_000      # portefeuille plus ancien : cible inconnue
    band_fraction: float = 0.02             # écart toléré avant d'agir (part de la valeur du compte)
    min_order_usd: float = MIN_ORDER_VALUE_USD
    taker_fee_bps: float = TAKER_PERP_BPS
    apply_spread: bool = True
    apply_funding: bool = True
    # Une journée ne compte que si le portefeuille du leader était CONNU pendant cette part de ses
    # pas : sinon la réplique ne fait que tenir un portefeuille périmé, ce qui ne mesure pas la stratégie.
    min_target_known_fraction: float = 0.9

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _Compte:
    """Compte de marge PAPER : liquidités + positions à prix moyen d'entrée."""

    liquidites: float
    positions: dict[str, float] = field(default_factory=dict)       # coin -> quantité signée
    entree: dict[str, float] = field(default_factory=dict)          # coin -> prix moyen d'entrée

    def valeur(self, prix: Mapping[str, float]) -> float:
        return self.liquidites + sum(q * (prix[c] - self.entree[c]) for c, q in self.positions.items())

    def notionnel(self, prix: Mapping[str, float]) -> float:
        return sum(abs(q) * prix[c] for c, q in self.positions.items())

    def traiter(self, coin: str, quantite: float, px: float) -> None:
        """Applique un ordre exécuté à ``px`` ; le PnL de la partie fermée rejoint les liquidités."""
        avant = self.positions.get(coin, 0.0)
        apres = avant + quantite
        if avant == 0.0 or (avant > 0) == (quantite > 0):                      # ouverture ou renfort
            self.entree[coin] = (abs(avant) * self.entree.get(coin, px) + abs(quantite) * px) / abs(apres)
        else:                                                                  # réduction, fermeture, retournement
            ferme = min(abs(quantite), abs(avant))
            self.liquidites += ferme * (px - self.entree[coin]) * (1.0 if avant > 0 else -1.0)
            if apres != 0.0 and (apres > 0) != (avant > 0):
                self.entree[coin] = px
        if abs(apres) < 1e-15:
            self.positions.pop(coin, None)
            self.entree.pop(coin, None)
        else:
            self.positions[coin] = apres


def _cible(portfolio: Portefeuille, instants: np.ndarray, t: int, config: ReplicationConfig,
           ) -> tuple[float, Mapping[str, float]] | None:
    """Dernier portefeuille OBSERVÉ avant ``t - réaction`` (jamais après), s'il est assez récent."""
    index = int(np.searchsorted(instants, t - config.reaction_ms, side="right")) - 1
    if index < 0:
        return None
    ts, nav, positions = portfolio[index]
    if t - ts > config.max_snapshot_age_ms or nav is None or not nav > 0:
        return None
    return float(nav), positions


def run_replication(
    portfolio: Portefeuille, panel: Any, half_spread_bps: Mapping[str, float],
    config: ReplicationConfig | None = None, *, funding_rates: Mapping[str, np.ndarray] | None = None,
    debut_grille_ms: int | None = None,
) -> dict[str, Any]:
    """Rejoue la réplication d'UN leader avec tout le capital.

    ``portfolio`` : ``(ts_ms, valeur_du_compte, {coin: taille})`` triés, portefeuilles COMPLETS.
    ``panel`` : série de prix causale (``ts``, ``column(coin)``, ``at(t, colonne)`` -> NaN si périmé).
    ``funding_rates`` : taux horaire par coin, aligné sur ``panel.ts`` (NaN = inconnu).
    ``debut_grille_ms`` : début imposé de la grille, pour comparer plusieurs réglages sur EXACTEMENT
    les mêmes instants (sinon un délai différent décale la fenêtre et fausse la comparaison).
    """
    config = config or ReplicationConfig()
    funding_rates = funding_rates or {}
    vide = {"status": "UNMEASURABLE", "complete_days": 0, "net_usd_per_day": None, "config": config.as_dict()}
    if not portfolio or len(getattr(panel, "ts", ())) < 2:
        return {**vide, "reason": "portefeuille ou prix absents"}
    instants = np.array([int(p[0]) for p in portfolio], dtype=np.int64)
    debut = max(int(instants[0]) + config.reaction_ms, int(panel.ts[0]), int(debut_grille_ms or 0))
    fin = min(int(instants[-1]) + config.max_snapshot_age_ms, int(panel.ts[-1]))
    premier = -(-debut // config.rebalance_ms) * config.rebalance_ms
    grille = [int(t) for t in np.arange(premier, fin + 1, config.rebalance_ms, dtype=np.int64)]
    if len(grille) < 2:
        return {**vide, "reason": "fenêtre commune portefeuilles / prix trop courte"}

    def prix_a(coin: str, t: int) -> float:
        colonne = panel.column(coin)
        return float("nan") if colonne is None else float(panel.at(np.array([t]), colonne)[0])

    def taux_funding(coin: str, t: int) -> float:
        serie = funding_rates.get(coin)
        index = int(np.searchsorted(panel.ts, t, side="right")) - 1
        return float("nan") if serie is None or index < 0 else float(serie[index])

    compte = _Compte(float(config.capital_usd))
    prix: dict[str, float] = {}                     # dernier prix SÛR de chaque coin détenu
    cumul = {"frais": 0.0, "ecart": 0.0, "funding": 0.0, "volume": 0.0}
    n = {"ordres": 0, "refus_min": 0, "refus_min_usd": 0.0, "cible_inconnue": 0,
         "funding_inconnu": 0.0, "funding_connu": 0.0}
    non_negociables: dict[str, str] = {}
    points: list[tuple[int, float, bool]] = []      # (instant, valeur du compte, valorisation sûre)
    cible_connue: dict[int, bool] = {}
    expositions: list[float] = []
    heures = config.rebalance_ms / 3_600_000.0

    for k, t in enumerate(grille):
        sur = True
        for coin, quantite in compte.positions.items():
            px = prix_a(coin, t)
            if k > 0 and config.apply_funding:
                taux = taux_funding(coin, grille[k - 1])
                notionnel = abs(quantite) * prix[coin]
                if np.isnan(taux):
                    n["funding_inconnu"] += notionnel * heures          # jamais supposé nul : compté à part
                else:
                    cout = quantite * prix[coin] * taux * heures         # un long paie un taux positif
                    compte.liquidites -= cout
                    cumul["funding"] += cout
                    n["funding_connu"] += notionnel * heures
            if np.isnan(px):
                sur = False                                              # prix périmé : valorisation inconnue
            else:
                prix[coin] = px
        valeur = compte.valeur(prix)
        points.append((t, valeur, sur))
        expositions.append(compte.notionnel(prix) / valeur if valeur > 0 else 0.0)
        cible = _cible(portfolio, instants, t, config)
        cible_connue[t] = cible is not None
        if cible is None:
            n["cible_inconnue"] += 1
            continue
        if not sur or valeur <= 0:
            continue
        nav, tailles = cible
        poids: dict[str, float] = {}
        for coin, taille in tailles.items():
            px = prix_a(coin, t)
            if np.isnan(px):
                non_negociables[coin] = "PRIX_INCONNU"
            elif config.apply_spread and coin not in half_spread_bps:
                non_negociables[coin] = "ECART_INCONNU"                  # coût non mesurable : pas d'ordre
            else:
                poids[coin] = float(taille) * px / nav
                prix[coin] = px
        brut = sum(abs(w) for w in poids.values())
        echelle = min(1.0, config.leverage_cap / brut) if brut > 0 else 0.0
        bande = config.band_fraction * valeur
        for coin in sorted(set(poids) | set(compte.positions)):
            if coin not in poids and coin in tailles:
                continue                                                 # coin non négociable : on ne force rien
            px = prix.get(coin, float("nan"))
            if np.isnan(px):
                continue
            actuel = compte.positions.get(coin, 0.0) * px
            voulu = poids.get(coin, 0.0) * echelle * valeur
            ecart = voulu - actuel
            fermeture_totale = voulu == 0.0 and actuel != 0.0            # toujours permise par la plateforme
            if not fermeture_totale and abs(ecart) < max(config.min_order_usd, bande):
                if abs(ecart) >= bande and abs(ecart) > 0.0:
                    n["refus_min"] += 1                                  # voulu par la stratégie, refusé par la plateforme
                    n["refus_min_usd"] += abs(ecart)
                continue
            demi_ecart = float(half_spread_bps.get(coin, 0.0)) if config.apply_spread else 0.0
            frais, cout_ecart = abs(ecart) * config.taker_fee_bps / 1e4, abs(ecart) * demi_ecart / 1e4
            compte.traiter(coin, ecart / px, px)
            compte.liquidites -= frais + cout_ecart
            cumul["frais"] += frais
            cumul["ecart"] += cout_ecart
            cumul["volume"] += abs(ecart)
            n["ordres"] += 1
    return _bilan(points, expositions, cumul, n, non_negociables, config, cible_connue)


def _bilan(points: list[tuple[int, float, bool]], expositions: list[float], cumul: Mapping[str, float],
           n: Mapping[str, Any], non_negociables: Mapping[str, str], config: ReplicationConfig,
           cible_connue: Mapping[int, bool]) -> dict[str, Any]:
    par_instant = {t: (valeur, sur) for t, valeur, sur in points}
    pas_par_jour = DAY_MS // config.rebalance_ms
    quotidiens: list[float] = []
    jours_comptes: list[int] = []
    jours_sans_cible = 0
    for jour in sorted({t // DAY_MS for t in par_instant}):
        bornes = [jour * DAY_MS + i * config.rebalance_ms for i in range(pas_par_jour + 1)]
        # journée COMPLÈTE : chaque pas présent et valorisé sûrement, ouverture du lendemain comprise
        if not all(t in par_instant and par_instant[t][1] for t in bornes):
            continue
        connus = sum(1 for t in bornes[:-1] if cible_connue.get(t))
        if connus < config.min_target_known_fraction * pas_par_jour:
            jours_sans_cible += 1                     # journée valorisée mais leader non observé : écartée
            continue
        quotidiens.append(par_instant[bornes[-1]][0] - par_instant[bornes[0]][0])
        jours_comptes.append(int(jour))
    serie = np.array([valeur for _, valeur, _ in points], dtype=float)
    duree_jours = max(1e-9, (points[-1][0] - points[0][0]) / DAY_MS)
    funding_total = n["funding_connu"] + n["funding_inconnu"]
    return {
        "status": "OK", "config": config.as_dict(),
        "complete_days": len(quotidiens),
        "daily_net_usd": [round(x, 6) for x in quotidiens], "days_utc": jours_comptes,
        "net_usd_per_day": float(np.mean(quotidiens)) if quotidiens else None,
        "final_equity_usd": float(serie[-1]), "net_total_usd": float(serie[-1] - config.capital_usd),
        "max_drawdown_usd": float((np.maximum.accumulate(serie) - serie).max()),
        "fees_usd": float(cumul["frais"]), "spread_cost_usd": float(cumul["ecart"]),
        "funding_usd": float(cumul["funding"]),
        "turnover_per_day": float(cumul["volume"] / config.capital_usd / duree_jours),
        "orders": int(n["ordres"]),
        "orders_refused_by_venue_minimum": int(n["refus_min"]),
        "orders_refused_by_venue_minimum_usd": float(n["refus_min_usd"]),
        "days_excluded_leader_unobserved": jours_sans_cible,
        "steps": len(points), "steps_target_unknown": int(n["cible_inconnue"]),
        "steps_valuation_unknown": int(sum(1 for _, _, sur in points if not sur)),
        "mean_gross_exposure": float(np.mean(expositions)) if expositions else 0.0,
        "funding_coverage": float(n["funding_connu"] / funding_total) if funding_total > 0 else None,
        "untradable_coins": dict(sorted(non_negociables.items())),
    }


def decomposer_les_pertes(
    portfolio: Portefeuille, panel: Any, half_spread_bps: Mapping[str, float],
    config: ReplicationConfig | None = None, *, funding_rates: Mapping[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Même trajectoire, frictions ajoutées une à une : ce que coûte chacune, en USD par jour."""
    config = config or ReplicationConfig()
    ideal = replace(config, reaction_ms=0, taker_fee_bps=0.0, apply_spread=False, apply_funding=False,
                    min_order_usd=0.0, band_fraction=0.0)
    delai = replace(ideal, reaction_ms=config.reaction_ms)
    frais = replace(delai, taker_fee_bps=config.taker_fee_bps, apply_spread=config.apply_spread)
    funding = replace(frais, apply_funding=config.apply_funding)
    etapes = [("sans_friction", ideal), ("avec_delai", delai), ("avec_frais_et_ecart", frais),
              ("avec_funding", funding), ("complet_ordre_minimal_et_bande", config)]
    # mêmes instants pour toutes les variantes : la grille part du réglage complet (délai compris)
    debut_commun = (int(portfolio[0][0]) + config.reaction_ms) if portfolio else None
    resultats = {nom: run_replication(portfolio, panel, half_spread_bps, cfg, funding_rates=funding_rates,
                                      debut_grille_ms=debut_commun)
                 for nom, cfg in etapes}
    nets = {nom: resultat.get("net_usd_per_day") for nom, resultat in resultats.items()}
    couts: dict[str, float | None] = {}
    for (precedent, _), (nom, _) in zip(etapes, etapes[1:]):
        connu = nets[precedent] is not None and nets[nom] is not None
        couts[nom] = float(nets[precedent] - nets[nom]) if connu else None
    return {"net_usd_per_day": nets, "cost_usd_per_day": couts, "full": resultats[etapes[-1][0]]}


def portefeuilles_depuis_instantanes(snapshots: Any) -> tuple[dict[str, list], dict[str, int]]:
    """``{compte: [(ts, valeur, {coin: taille}), ...]}`` depuis des instantanés certifiés.

    Seuls les portefeuilles COMPLETS du dex principal sont gardés : celui d'un dex HIP-3 ne contient
    pas les autres positions du compte et ne peut pas être lu comme le portefeuille entier.
    """
    par_compte: dict[str, dict[int, tuple[float | None, dict[str, float]]]] = {}
    rejets: dict[str, int] = {}
    for snap in snapshots:
        compte, ts, positions = str(snap.get("vault") or "").lower(), snap.get("ts_ms"), snap.get("positions")
        if snap.get("dex"):
            rejets["portefeuille_autre_dex"] = rejets.get("portefeuille_autre_dex", 0) + 1
            continue
        if not compte or type(ts) is not int or ts <= 0 or not isinstance(positions, list):
            rejets["instantane_invalide"] = rejets.get("instantane_invalide", 0) + 1
            continue
        tailles: dict[str, float] = {}
        try:
            for position in positions:
                taille = float(position["szi"])
                if not np.isfinite(taille) or not position.get("coin"):
                    raise ValueError
                tailles[str(position["coin"])] = taille
        except (KeyError, TypeError, ValueError):
            rejets["position_illisible"] = rejets.get("position_illisible", 0) + 1
            continue
        nav = snap.get("nav_usd")
        nav = float(nav) if isinstance(nav, (int, float)) and not isinstance(nav, bool) and np.isfinite(nav) else None
        par_compte.setdefault(compte, {}).setdefault(ts, (nav, tailles))
    return ({compte: [(ts, *par_compte[compte][ts]) for ts in sorted(par_compte[compte])]
             for compte in sorted(par_compte)}, rejets)


def synthese_replication(par_leader: Mapping[str, Mapping[str, Any]], config: ReplicationConfig | None = None, *,
                         min_days: int = 20, bootstrap_samples: int = 2_000, seed: int = 20_261_111) -> dict[str, Any]:
    """Résultat d'ensemble : un compte de 350 USD confié à UN leader, moyenne sur les leaders.

    L'incertitude est tirée par JOURNÉE (toutes les répliques d'un même jour bougent ensemble : les
    compter comme indépendantes gonflerait la précision). Règles fixées avant la mesure : moins de
    ``min_days`` journées distinctes -> MORE_DATA ; intervalle entièrement négatif -> REJECTED ;
    entièrement positif ET funding couvert à 95 % -> PROMISING ; sinon MORE_DATA.
    """
    config = config or ReplicationConfig()
    par_jour: dict[int, list[float]] = {}
    for resultat in par_leader.values():
        complet = resultat["full"]
        for jour, net in zip(complet.get("days_utc") or (), complet.get("daily_net_usd") or ()):
            par_jour.setdefault(int(jour), []).append(float(net))
    base = {"hypothesis": H_REPLICATION_350, "economically_proven": False, "leaders": len(par_leader),
            "leaders_measured": sum(1 for r in par_leader.values() if r["full"].get("complete_days")),
            "distinct_days": len(par_jour), "leader_days": sum(len(v) for v in par_jour.values())}
    if not par_jour:
        return {**base, "status": "MORE_DATA", "reason": "aucune journée complète mesurable",
                "net_usd_per_day": None, "interval_95": None}
    moyennes = np.array([np.mean(v) for _, v in sorted(par_jour.items())], dtype=float)
    rng = np.random.default_rng(seed)
    tirages = moyennes[rng.integers(0, moyennes.size, size=(bootstrap_samples, moyennes.size))].mean(axis=1)
    bas, haut = (float(np.quantile(tirages, 0.025)), float(np.quantile(tirages, 0.975))) if moyennes.size > 1 \
        else (float("nan"), float("nan"))
    couvertures = [r["full"]["funding_coverage"] for r in par_leader.values() if r["full"].get("funding_coverage") is not None]
    couverture = float(np.mean(couvertures)) if couvertures else None
    couts: dict[str, float] = {}
    for nom in ("avec_delai", "avec_frais_et_ecart", "avec_funding", "complet_ordre_minimal_et_bande"):
        valeurs = [r["cost_usd_per_day"][nom] for r in par_leader.values() if r["cost_usd_per_day"].get(nom) is not None]
        if valeurs:
            couts[nom] = float(np.mean(valeurs))
    net = float(moyennes.mean())
    corps = {**base, "net_usd_per_day": net, "interval_95": (bas, haut), "funding_coverage": couverture,
             "net_bps_per_day_on_capital": net / config.capital_usd * 1e4, "mean_cost_usd_per_day": couts,
             "share_positive_days": float((moyennes > 0).mean())}
    if len(par_jour) < min_days:
        return {**corps, "status": "MORE_DATA",
                "reason": f"{len(par_jour)} journée(s) distincte(s) mesurée(s) ; il en faut au moins {min_days}"}
    if haut <= 0:
        return {**corps, "status": "REJECTED", "reason": "résultat net négatif après coûts sur toute la plage de confiance"}
    if bas > 0 and couverture is not None and couverture >= 0.95:
        return {**corps, "status": "PROMISING",
                "reason": "net positif après frais, écart, funding et ordre minimal ; à confirmer hors échantillon"}
    return {**corps, "status": "MORE_DATA",
            "reason": "intervalle à cheval sur zéro, ou funding insuffisamment couvert pour conclure"}


__all__ = ["H_REPLICATION_350", "ReplicationConfig", "decomposer_les_pertes", "portefeuilles_depuis_instantanes",
           "run_replication", "synthese_replication"]

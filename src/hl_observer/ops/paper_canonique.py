"""§5/§6/§7 — moteur paper CANONIQUE unique, exécution réaliste, runtime-truth (lecture seule, 0 réseau).

Le projet a accumulé des vérités comptables PARALLÈLES (experimental paper, cohortes RAW/PROBE/ALPHA,
carry legacy). Deux stratégies peuvent avoir des SIGNAUX différents ; elles ne doivent JAMAIS avoir une
comptabilité différente. Ce module fixe le contrat unique, en composant sur les briques déjà canoniques :

  * exécution / ledger de vérité : `hl_observer.market_truth` (déjà branché, §5 pipeline) ;
  * équity liquidable sans double comptage : `equity_canonique` (§4.5) ;
  * appariement en lots avec REDUCE partiel : `economic_revalidation.normaliser_episodes` (§4.1).

Il ajoute ce qui manquait, en pur, testable et honnête :

§5  — `PaperIntent` : le contrat d'intention commun à toutes les voies (cross-venue, lead-lag, copy, TWAP).
§6.2 — `LiquidityConsumptionLedger` : une profondeur consommée par un fill paper ne peut pas être
       reconsommée par un second ordre avant refresh du carnet (`snapshot_version`).
§6.3 — `remplir_partiellement` : taille > profondeur ⇒ on remplit l'exécutable, le reste est un résidu
       EXPLICITE, jamais un fill inventé.
§6.4 — `fill_maker` : sans file mesurée, `MAKER_FILL_UNMEASURABLE` — jamais « le prix a touché donc rempli ».
§6.5 — `carnet_fiable` : gap de séquence, stale, out-of-order, reconnect ⇒ entrée interdite.
§7  — `runtime_truth` : par stratégie, producteur vivant ? dernier événement ? moteur/ledger prêts ?

Le carry n'apparaît nulle part comme stratégie active : le scope est cross-venue + lead-lag + copy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from hl_observer.strategies.active_scope import (
    active_strategy_families as _active_strategy_families,
    strategy_scope_status as _strategy_scope_status,
    StrategyScopeStatus as _StrategyScopeStatus,
)

SCHEMA_VERSION = "hypersmart.paper_canonique.v1"

#: P0 — UNE SEULE vérité de scope : `strategies.active_scope` est l'autorité UNIQUE. Ce module ne
#: redéclare AUCUNE allowlist concurrente ; il DÉRIVE l'ensemble matérialisant de l'autorité. Une
#: famille SHADOW (ex. twap_metaorder) ou DISABLED (carry/funding) ne peut donc JAMAIS émettre un
#: intent économique via paper_canonique — même si une liste locale réapparaissait ailleurs.
STRATEGIES_ACTIVES: tuple[str, ...] = tuple(sorted(_active_strategy_families()))
#: Familles legacy neutralisées : jamais de signal, PnL, capital ni influence scoreboard.
STRATEGIES_LEGACY_OFF = ("carry", "funding", "triangular", "market_making")


class ScopeViolation(ValueError):
    """Une voie hors allowlist tente d'émettre un intent. Refusé au point d'émission, pas en aval."""


@dataclass(frozen=True)
class PaperIntent:
    """§5 — contrat d'intention UNIQUE. Toute voie passe par lui avant tout fill.

    `strategy` doit appartenir à l'allowlist active : une famille legacy (carry…) ne peut pas fabriquer
    un intent, donc ne peut ni consommer de capital ni influencer le scoreboard.
    """

    strategy: str
    coin: str
    side: int                       # +1 achat, -1 vente
    notional_usd: float
    signal_observable_at_ms: int
    venue: str = "HL"
    intent_id: str = ""
    cohort: str = "STRICT"

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES_ACTIVES:
            raise ScopeViolation(
                "strategie hors scope actif: %r (actives: %s)" % (self.strategy, ", ".join(STRATEGIES_ACTIVES)))
        if self.side not in (1, -1):
            raise ValueError("side doit valoir +1 ou -1")

    def as_dict(self) -> dict[str, Any]:
        return {"strategy": self.strategy, "coin": self.coin.upper(), "side": self.side,
                "notional_usd": self.notional_usd, "venue": self.venue,
                "signal_observable_at_ms": self.signal_observable_at_ms,
                "intent_id": self.intent_id, "cohort": self.cohort,
                "paper_only": True, "real_execution": False}


def strategie_autorisee(strategy: str) -> bool:
    return str(strategy) in STRATEGIES_ACTIVES


# ════════════════════════ §6.2 — consommation de liquidité ════════════════════════
@dataclass
class LiquidityConsumptionLedger:
    """Une unité de profondeur consommée par un fill paper est indisponible jusqu'au refresh du carnet.

    Clé : `(venue, coin, side, price_level, snapshot_version)`. Un second ordre sur le MÊME snapshot ne peut
    pas re-remplir les mêmes unités : sans ça, la simulation sur-remplit la liquidité affichée et fabrique
    une capacité qui n'existe pas.
    """

    _consomme: dict[tuple, float] = field(default_factory=dict)

    def disponible(self, *, venue: str, coin: str, side: int, price_level: float,
                   snapshot_version: Any, profondeur_affichee: float) -> float:
        cle = (str(venue).upper(), str(coin).upper(), int(side), round(float(price_level), 10),
               str(snapshot_version))
        return max(0.0, float(profondeur_affichee) - self._consomme.get(cle, 0.0))

    def consommer(self, *, venue: str, coin: str, side: int, price_level: float,
                  snapshot_version: Any, quantite: float, profondeur_affichee: float) -> dict[str, Any]:
        dispo = self.disponible(venue=venue, coin=coin, side=side, price_level=price_level,
                                snapshot_version=snapshot_version, profondeur_affichee=profondeur_affichee)
        pris = max(0.0, min(float(quantite), dispo))
        cle = (str(venue).upper(), str(coin).upper(), int(side), round(float(price_level), 10),
               str(snapshot_version))
        self._consomme[cle] = self._consomme.get(cle, 0.0) + pris
        return {"consomme": pris, "refuse": max(0.0, float(quantite) - pris),
                "restant_apres": max(0.0, dispo - pris)}


# ════════════════════════ §6.3 — fills partiels ════════════════════════
def remplir_partiellement(taille_demandee: float, niveaux: Sequence[tuple[float, float]]) -> dict[str, Any]:
    """Marche le carnet niveau par niveau. `niveaux` = [(prix, profondeur)]. Le résidu est EXPLICITE.

    Une taille supérieure à la profondeur totale ne se remplit jamais entièrement : on rend ce qui est
    réellement exécutable + un `residu` nommé, jamais un fill complet inventé.
    """
    reste = float(taille_demandee)
    if reste <= 0:
        return {"rempli": 0.0, "residu": 0.0, "vwap": None, "statut": "TAILLE_NULLE"}
    rempli = 0.0
    cout = 0.0
    for prix, profondeur in niveaux:
        p, d = float(prix), max(0.0, float(profondeur))
        if p <= 0 or d <= 0:
            continue
        pris = min(reste, d)
        rempli += pris
        cout += pris * p
        reste -= pris
        if reste <= 1e-12:
            break
    vwap = (cout / rempli) if rempli > 0 else None
    return {"rempli": round(rempli, 10), "residu": round(max(0.0, reste), 10),
            "vwap": (None if vwap is None else round(vwap, 10)),
            "fill_ratio": (round(rempli / float(taille_demandee), 6) if taille_demandee else None),
            "statut": "COMPLET" if reste <= 1e-12 else "PARTIEL",
            "real_execution": False}


# ════════════════════════ §6.4 — fill maker ════════════════════════
def fill_maker(*, file_devant_nous: float | None, volume_traversant: float | None,
               taille: float) -> dict[str, Any]:
    """Un maker n'est PAS rempli parce que le prix a touché. Sans file ni volume mesurés :
    `MAKER_FILL_UNMEASURABLE`. Avec les deux : le fill est borné par le volume au-delà de la file."""
    if file_devant_nous is None or volume_traversant is None:
        return {"statut": "MAKER_FILL_UNMEASURABLE", "rempli": None,
                "raison": "file devant nous ou volume traversant non mesures : aucun fill suppose"}
    reste_apres_file = max(0.0, float(volume_traversant) - float(file_devant_nous))
    rempli = max(0.0, min(float(taille), reste_apres_file))
    return {"statut": "MAKER_FILL_MODELISE", "rempli": round(rempli, 10),
            "fill_ratio": (round(rempli / float(taille), 6) if taille else None),
            "note": "modele conservateur : rempli seulement par le volume au-dela de la file",
            "real_execution": False}


# ════════════════════════ §6.5 — fiabilité du carnet ════════════════════════
def carnet_fiable(*, sequence: int | None, derniere_sequence: int | None, age_ms: float | None,
                  age_max_ms: float, skew_ms: float | None = None, skew_max_ms: float = 1_000.0) -> dict[str, Any]:
    """Un carnet non fiable INTERDIT l'entrée. Gap de séquence, stale, skew d'horloge, séquence absente."""
    raisons: list[str] = []
    if sequence is None or derniere_sequence is None:
        raisons.append("SEQUENCE_ABSENTE")
    elif int(sequence) < int(derniere_sequence):
        raisons.append("OUT_OF_ORDER")
    elif int(sequence) > int(derniere_sequence) + 1:
        raisons.append("GAP_DE_SEQUENCE")
    if age_ms is None:
        raisons.append("AGE_INCONNU")
    elif float(age_ms) > float(age_max_ms):
        raisons.append("STALE")
    if skew_ms is not None and abs(float(skew_ms)) > float(skew_max_ms):
        raisons.append("SKEW_HORLOGE")
    return {"fiable": not raisons, "entree_autorisee": not raisons, "raisons": raisons}


# ════════════════════════ §7 — runtime-truth ════════════════════════
def runtime_truth(observations: Mapping[str, Mapping[str, Any]], *, now_ms: int,
                  age_max_ms: float = 120_000.0) -> dict[str, Any]:
    """Par stratégie ACTIVE : producteur vivant ? dernier événement récent ? moteur/ledger prêts ?

    Un flag « ON » sans producteur vivant est déclaré `ON_SANS_PRODUCTEUR` — c'est-à-dire OFF de fait.
    Les familles legacy sont listées à part, toujours `DISABLED_BY_SCOPE`.
    """
    lignes: dict[str, Any] = {}
    for strat in STRATEGIES_ACTIVES:
        o = dict(observations.get(strat) or {})
        dernier = o.get("last_event_ms")
        age = None if not isinstance(dernier, (int, float)) else float(now_ms) - float(dernier)
        producteur = bool(o.get("producer_alive")) and age is not None and age <= float(age_max_ms)
        signal = bool(o.get("signal_path_alive"))
        moteur = bool(o.get("execution_engine_alive"))
        ledger = bool(o.get("ledger_writable"))
        if not producteur:
            etat = "ON_SANS_PRODUCTEUR" if o.get("flag_on") else "OFF"
        elif signal and moteur and ledger:
            etat = "VIVANT"
        else:
            etat = "PRODUCTEUR_SANS_CHAINE_COMPLETE"
        lignes[strat] = {
            "etat": etat, "producer_alive": producteur, "last_event_age_ms": (None if age is None else round(age, 1)),
            "signal_path_alive": signal, "execution_engine_alive": moteur, "ledger_writable": ledger,
            "last_decision": o.get("last_decision"), "last_refusal_reason": o.get("last_refusal_reason")}
    return {"schema_version": SCHEMA_VERSION, "strategies_actives": lignes,
            "legacy_off": {s: "DISABLED_BY_SCOPE" for s in STRATEGIES_LEGACY_OFF},
            "real_execution": False}


__all__ = ["SCHEMA_VERSION", "STRATEGIES_ACTIVES", "STRATEGIES_LEGACY_OFF", "ScopeViolation",
           "PaperIntent", "strategie_autorisee", "LiquidityConsumptionLedger", "remplir_partiellement",
           "fill_maker", "carnet_fiable", "runtime_truth"]

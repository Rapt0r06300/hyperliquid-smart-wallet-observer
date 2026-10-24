"""§5/§6/§7 — moteur paper CANONIQUE unique, exécution réaliste, runtime-truth (lecture seule, 0 réseau).

Le projet a accumulé des vérités comptables PARALLÈLES (experimental paper, cohortes RAW/PROBE/ALPHA,
carry legacy). Deux stratégies peuvent avoir des SIGNAUX différents ; elles ne doivent JAMAIS avoir une
comptabilité différente. Ce module fixe le contrat unique, en composant sur les briques déjà canoniques :

  * exécution / ledger de vérité : `hl_observer.market_truth` (déjà branché, §5 pipeline) ;
  * équity liquidable sans double comptage : `equity_canonique` (§4.5) ;
  * appariement en lots avec REDUCE partiel : `economic_revalidation.normaliser_episodes` (§4.1).

Il ajoute ce qui manquait, en pur, testable et honnête :

§5  — `PaperIntent` : le contrat d'intention commun, actuellement limité à CopyVault.
§6.2 — `LiquidityConsumptionLedger` : une profondeur consommée par un fill paper ne peut pas être
       reconsommée par un second ordre avant refresh du carnet (`snapshot_version`).
§6.3 — `remplir_partiellement` : taille > profondeur ⇒ on remplit l'exécutable, le reste est un résidu
       EXPLICITE, jamais un fill inventé.
§6.4 — `fill_maker` : sans file mesurée, `MAKER_FILL_UNMEASURABLE` — jamais « le prix a touché donc rempli ».
§6.5 — `carnet_fiable` : gap de séquence, stale, out-of-order, reconnect ⇒ entrée interdite.
§7  — `runtime_truth` : par stratégie, producteur vivant ? dernier événement ? moteur/ledger prêts ?

CopyVault est la seule stratégie active; les autres familles restent visibles mais hors exécution.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hl_observer.strategies.active_scope import (
    active_strategy_families as _active_strategy_families,
)
from hl_observer.strategies.active_scope import (
    authoritative_strategy_scope as _authoritative_strategy_scope,
)

SCHEMA_VERSION = "hypersmart.paper_canonique.v1"

#: P0 — UNE SEULE vérité de scope : `strategies.active_scope` est l'autorité UNIQUE. Ce module ne
#: redéclare AUCUNE allowlist concurrente ; il DÉRIVE l'ensemble matérialisant de l'autorité. Une
#: famille SHADOW (ex. twap_metaorder) ou DISABLED (carry/funding) ne peut donc JAMAIS émettre un
#: intent économique via paper_canonique — même si une liste locale réapparaissait ailleurs.
STRATEGIES_ACTIVES: tuple[str, ...] = tuple(sorted(_active_strategy_families()))
#: Familles legacy neutralisées : jamais de signal, PnL, capital ni influence scoreboard.
STRATEGIES_LEGACY_OFF = tuple(sorted(
    entry.family for entry in _authoritative_strategy_scope()
    if entry.family not in STRATEGIES_ACTIVES
))


def _finite_number(value: Any, *, name: str) -> float:
    """Return one finite real value or fail before economic arithmetic."""

    if isinstance(value, bool):
        raise ValueError(f"{name} doit etre un nombre fini")
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} doit etre un nombre fini") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{name} doit etre un nombre fini")
    return converted


def _non_empty(value: Any, *, name: str) -> str:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} ne doit pas etre vide")
    converted = str(value).strip()
    if not converted:
        raise ValueError(f"{name} ne doit pas etre vide")
    return converted


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
        if isinstance(self.side, bool) or self.side not in (1, -1):
            raise ValueError("side doit valoir +1 ou -1")
        coin = _non_empty(self.coin, name="coin").upper()
        venue = _non_empty(self.venue, name="venue").upper()
        notional = _finite_number(self.notional_usd, name="notional_usd")
        if notional <= 0.0:
            raise ValueError("notional_usd doit etre strictement positif")
        if (
            isinstance(self.signal_observable_at_ms, bool)
            or not isinstance(self.signal_observable_at_ms, int)
            or self.signal_observable_at_ms <= 0
        ):
            raise ValueError("signal_observable_at_ms doit etre un entier positif")
        object.__setattr__(self, "coin", coin)
        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "notional_usd", notional)

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

    @staticmethod
    def _cle_validee(*, venue: str, coin: str, side: int, price_level: float,
                     snapshot_version: Any, profondeur_affichee: float) -> tuple[tuple, float]:
        venue_normalisee = _non_empty(venue, name="venue").upper()
        coin_normalise = _non_empty(coin, name="coin").upper()
        if isinstance(side, bool) or side not in (1, -1):
            raise ValueError("side doit valoir +1 ou -1")
        prix = _finite_number(price_level, name="price_level")
        profondeur = _finite_number(profondeur_affichee, name="profondeur_affichee")
        if prix <= 0.0:
            raise ValueError("price_level doit etre strictement positif")
        if profondeur < 0.0:
            raise ValueError("profondeur_affichee doit etre positive ou nulle")
        version = _non_empty(snapshot_version, name="snapshot_version")
        return (venue_normalisee, coin_normalise, int(side), round(prix, 10), version), profondeur

    def disponible(self, *, venue: str, coin: str, side: int, price_level: float,
                   snapshot_version: Any, profondeur_affichee: float) -> float:
        cle, profondeur = self._cle_validee(
            venue=venue, coin=coin, side=side, price_level=price_level,
            snapshot_version=snapshot_version, profondeur_affichee=profondeur_affichee,
        )
        return max(0.0, profondeur - self._consomme.get(cle, 0.0))

    def consommer(self, *, venue: str, coin: str, side: int, price_level: float,
                  snapshot_version: Any, quantite: float, profondeur_affichee: float) -> dict[str, Any]:
        quantite_validee = _finite_number(quantite, name="quantite")
        if quantite_validee < 0.0:
            raise ValueError("quantite doit etre positive ou nulle")
        dispo = self.disponible(venue=venue, coin=coin, side=side, price_level=price_level,
                                snapshot_version=snapshot_version, profondeur_affichee=profondeur_affichee)
        pris = min(quantite_validee, dispo)
        cle, _ = self._cle_validee(
            venue=venue, coin=coin, side=side, price_level=price_level,
            snapshot_version=snapshot_version, profondeur_affichee=profondeur_affichee,
        )
        self._consomme[cle] = self._consomme.get(cle, 0.0) + pris
        return {"consomme": pris, "refuse": max(0.0, quantite_validee - pris),
                "restant_apres": max(0.0, dispo - pris)}


# ════════════════════════ §6.3 — fills partiels ════════════════════════
def remplir_partiellement(taille_demandee: float, niveaux: Sequence[tuple[float, float]]) -> dict[str, Any]:
    """Marche le carnet niveau par niveau. `niveaux` = [(prix, profondeur)]. Le résidu est EXPLICITE.

    Une taille supérieure à la profondeur totale ne se remplit jamais entièrement : on rend ce qui est
    réellement exécutable + un `residu` nommé, jamais un fill complet inventé.
    """
    reste = _finite_number(taille_demandee, name="taille_demandee")
    if reste < 0.0:
        raise ValueError("taille_demandee doit etre positive ou nulle")
    if reste == 0.0:
        return {"rempli": 0.0, "residu": 0.0, "vwap": None, "statut": "TAILLE_NULLE"}
    rempli = 0.0
    cout = 0.0
    for prix, profondeur in niveaux:
        p = _finite_number(prix, name="prix")
        d = _finite_number(profondeur, name="profondeur")
        if p <= 0.0 or d < 0.0:
            raise ValueError("prix doit etre positif et profondeur positive ou nulle")
        if d == 0.0:
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
    taille_validee = _finite_number(taille, name="taille")
    if taille_validee <= 0.0:
        raise ValueError("taille doit etre strictement positive")
    if file_devant_nous is None or volume_traversant is None:
        return {"statut": "MAKER_FILL_UNMEASURABLE", "rempli": None,
                "raison": "file devant nous ou volume traversant non mesures : aucun fill suppose"}
    file_validee = _finite_number(file_devant_nous, name="file_devant_nous")
    volume_valide = _finite_number(volume_traversant, name="volume_traversant")
    if file_validee < 0.0 or volume_valide < 0.0:
        raise ValueError("file_devant_nous et volume_traversant doivent etre positifs ou nuls")
    reste_apres_file = max(0.0, volume_valide - file_validee)
    rempli = min(taille_validee, reste_apres_file)
    return {"statut": "MAKER_FILL_MODELISE", "rempli": round(rempli, 10),
            "fill_ratio": round(rempli / taille_validee, 6),
            "note": "modele conservateur : rempli seulement par le volume au-dela de la file",
            "real_execution": False}


# ════════════════════════ §6.5 — fiabilité du carnet ════════════════════════
def carnet_fiable(*, sequence: int | None, derniere_sequence: int | None, age_ms: float | None,
                  age_max_ms: float, skew_ms: float | None = None, skew_max_ms: float = 1_000.0) -> dict[str, Any]:
    """Un carnet non fiable INTERDIT l'entrée. Gap de séquence, stale, skew d'horloge, séquence absente."""
    raisons: list[str] = []
    if sequence is None or derniere_sequence is None:
        raisons.append("SEQUENCE_ABSENTE")
    else:
        try:
            sequence_validee = _finite_number(sequence, name="sequence")
            derniere_validee = _finite_number(
                derniere_sequence, name="derniere_sequence"
            )
            if (
                sequence_validee < 0.0
                or derniere_validee < 0.0
                or not sequence_validee.is_integer()
                or not derniere_validee.is_integer()
            ):
                raise ValueError("sequences entieres positives requises")
            if sequence_validee < derniere_validee:
                raisons.append("OUT_OF_ORDER")
            elif sequence_validee > derniere_validee + 1:
                raisons.append("GAP_DE_SEQUENCE")
        except ValueError:
            raisons.append("SEQUENCE_INVALIDE")
    if age_ms is None:
        raisons.append("AGE_INCONNU")
    else:
        try:
            age = _finite_number(age_ms, name="age_ms")
            age_max = _finite_number(age_max_ms, name="age_max_ms")
            if age_max < 0.0:
                raise ValueError("age_max_ms doit etre positif ou nul")
            if age < 0.0:
                raisons.append("OBSERVATION_DANS_LE_FUTUR")
            elif age > age_max:
                raisons.append("STALE")
        except ValueError:
            raisons.append("AGE_INVALIDE")
    if skew_ms is not None:
        try:
            skew = _finite_number(skew_ms, name="skew_ms")
            skew_max = _finite_number(skew_max_ms, name="skew_max_ms")
            if skew_max < 0.0:
                raise ValueError("skew_max_ms doit etre positif ou nul")
            if abs(skew) > skew_max:
                raisons.append("SKEW_HORLOGE")
        except ValueError:
            raisons.append("SKEW_INVALIDE")
    return {"fiable": not raisons, "entree_autorisee": not raisons, "raisons": raisons}


# ════════════════════════ §7 — runtime-truth ════════════════════════
def runtime_truth(observations: Mapping[str, Mapping[str, Any]], *, now_ms: int,
                  age_max_ms: float = 120_000.0) -> dict[str, Any]:
    """Par stratégie ACTIVE : producteur vivant ? dernier événement récent ? moteur/ledger prêts ?

    Un flag « ON » sans producteur vivant est déclaré `ON_SANS_PRODUCTEUR` — c'est-à-dire OFF de fait.
    Les familles legacy sont listées à part, toujours `DISABLED_BY_SCOPE`.
    """
    lignes: dict[str, Any] = {}
    try:
        maintenant = _finite_number(now_ms, name="now_ms")
        age_max = _finite_number(age_max_ms, name="age_max_ms")
        if age_max < 0.0:
            raise ValueError("age_max_ms doit etre positif ou nul")
    except ValueError:
        maintenant = math.nan
        age_max = math.nan
    for strat in STRATEGIES_ACTIVES:
        o = dict(observations.get(strat) or {})
        dernier = o.get("last_event_ms")
        try:
            dernier_valide = _finite_number(dernier, name="last_event_ms")
            age = maintenant - dernier_valide
        except ValueError:
            age = None
        producteur = bool(
            o.get("producer_alive")
            and age is not None
            and math.isfinite(age)
            and 0.0 <= age <= age_max
        )
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

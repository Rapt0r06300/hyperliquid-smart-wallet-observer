"""LATENCE BOUT EN BOUT — horloge MONOTONE, étapes séparées (2026-07-11). Phase 3 du brief.

CE QUI EXISTAIT, ET POURQUOI ÇA NE SUFFIT PAS.

`realtime/latency_report.py` ne rapporte QU'UN SEUL chiffre : `signal_age_ms`. Il ne dit rien de
ce qui se passe DANS le pipeline. Or les logs montrent un cycle de poll median a **30,6 s**
(p95 50,4 s, max 106 s) : le temps ne se perd pas "quelque part", il se perd a des endroits
PRECIS -- et sans mesure par etape, on ne peut que deviner lequel.

Pire : `signal_age_ms` est obtenu en soustrayant un horodatage d'EXCHANGE d'une horloge LOCALE.
Les deux horloges ne sont pas synchronisees. **Le brief l'interdit explicitement**, et il a raison :
un decalage d'horloge de 200 ms se lit alors comme 200 ms de latence -- ou l'inverse, il peut MASQUER
200 ms de vraie latence. On mesurerait notre propre derive d'horloge en croyant mesurer le reseau.

CE MODULE POSE LA REGLE :

    * duree LOCALE  -> horloge MONOTONE (`perf_counter_ns`). Elle ne recule jamais, ne saute
      jamais a l'heure d'ete, ne depend d'aucun serveur NTP.
    * age SOURCE    -> horloge murale, et **rapporte SEPAREMENT**. On ne l'additionne JAMAIS
      aux durees locales pour fabriquer un "total" qui melangerait deux referentiels.

Ces deux nombres repondent a deux questions differentes :
    "le signal etait-il vieux quand il est arrive ?"      (age source)
    "combien de temps l'avons-nous garde avant d'agir ?"  (traitement local)
**Les confondre, c'est ne pouvoir corriger ni l'un ni l'autre.**

PUR, sans I/O reseau. Aucun ordre reel.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

# Les etapes du chemin critique, dans l'ordre. Une etape absente est RAPPORTEE comme absente,
# jamais remplacee par zero (un zero silencieux ferait croire a une etape instantanee).
ETAPES = (
    "receive",              # l'evenement arrive du WebSocket
    "decode",               # JSON -> objets
    "normalize",            # mise en forme interne
    "dedupe",               # doublons / hors-ordre
    "state_update",         # mise a jour de l'etat memoire
    "features",             # calcul des features
    "signal",               # detection du signal
    "score",                # scoring
    "gates",                # gates edge / cout / liquidite / risque
    "decision",             # decision finale
    "intent",               # intention paper
    "persist",              # ecriture (hors chemin critique en cible)
)


def _now_ns() -> int:
    """Horloge MONOTONE. Ne recule jamais. C'est la SEULE valide pour une duree locale."""
    return time.perf_counter_ns()


@dataclass(slots=True)
class LatencyTrace:
    """La trace d'UN evenement, du WebSocket a la decision.

    `source_event_time_ms` (heure EXCHANGE) est conservee, mais JAMAIS melangee aux durees
    locales : elle repond a une autre question.
    """

    event_id: str = ""
    strategy_mode: str = ""
    coin: str = ""
    source: str = ""
    source_event_time_ms: int | None = None       # heure EXCHANGE (murale)
    local_receive_wall_ms: int | None = None      # heure LOCALE murale, pour l'age source
    _stamps_ns: dict[str, int] = field(default_factory=dict)

    def start(self) -> "LatencyTrace":
        self.local_receive_wall_ms = int(time.time() * 1000)
        self._stamps_ns["receive"] = _now_ns()
        return self

    def stamp(self, etape: str) -> "LatencyTrace":
        """Horodate une etape. Une etape inconnue est IGNOREE (on n'invente pas de mesure)."""
        if etape in ETAPES:
            self._stamps_ns[etape] = _now_ns()
        return self

    # ---------------------------------------------------------------- les deux questions

    def source_age_ms(self) -> float | None:
        """« Le signal etait-il DEJA vieux en arrivant ? » -- horloge murale, des deux cotes.

        None si l'un des deux horodatages manque : on ne fabrique pas un age.
        ⚠️ Cet age contient le decalage d'horloge entre l'exchange et nous. Il n'est PAS une
        mesure de notre latence -- et ne doit jamais etre additionne aux durees locales.
        """
        if self.source_event_time_ms is None or self.local_receive_wall_ms is None:
            return None
        return float(self.local_receive_wall_ms - self.source_event_time_ms)

    def local_processing_ms(self, jusqu_a: str = "decision") -> float | None:
        """« Combien de temps l'avons-nous GARDE avant d'agir ? » -- horloge MONOTONE.

        C'est la seule duree que nous controlons, et donc la seule que nous puissions corriger.
        """
        debut = self._stamps_ns.get("receive")
        fin = self._stamps_ns.get(jusqu_a)
        if debut is None or fin is None:
            return None
        return (fin - debut) / 1e6

    def stage_durations_ms(self) -> dict[str, float]:
        """Duree de CHAQUE etape. Une etape non horodatee est ABSENTE du resultat -- pas a zero."""
        out: dict[str, float] = {}
        precedente_ns: int | None = None
        precedente_nom = ""
        for etape in ETAPES:
            ns = self._stamps_ns.get(etape)
            if ns is None:
                continue
            if precedente_ns is not None:
                out[f"{precedente_nom}->{etape}"] = (ns - precedente_ns) / 1e6
            precedente_ns, precedente_nom = ns, etape
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "strategy_mode": self.strategy_mode,
            "coin": self.coin,
            "source": self.source,
            # SEPARES, et etiquetes comme tels. Les additionner serait une faute de mesure.
            "source_age_ms": self.source_age_ms(),
            "local_processing_ms": self.local_processing_ms(),
            "stage_durations_ms": {k: round(v, 4) for k, v in self.stage_durations_ms().items()},
            "clock_note": "source_age = horloge murale (contient le decalage d'horloge) ; "
                          "local_processing = horloge MONOTONE. Ne jamais additionner.",
        }


# ---------------------------------------------------------------------- statistiques honnetes


def _percentile(valeurs: list[float], p: float) -> float | None:
    if not valeurs:
        return None
    v = sorted(valeurs)
    i = min(len(v) - 1, max(0, int(round((len(v) - 1) * p))))
    return v[i]


def resumer(traces: Iterable[LatencyTrace]) -> dict[str, Any]:
    """n / min / mediane / p90 / p95 / p99 / max + **taux de valeurs manquantes**.

    Le taux de manquants n'est pas un detail : une mediane calculee sur 3 % des evenements ne
    decrit pas le systeme. On le dit, plutot que d'exhiber un joli chiffre non representatif.
    """
    traces = list(traces)
    total = len(traces)

    def _stats(nom: str, valeurs: list[float]) -> dict[str, Any]:
        n = len(valeurs)
        return {
            "n": n,
            "manquants": total - n,
            "taux_manquant": (round((total - n) / total, 4) if total else None),
            "min": (round(min(valeurs), 4) if valeurs else None),
            "mediane": (round(_percentile(valeurs, 0.50), 4) if valeurs else None),
            "p90": (round(_percentile(valeurs, 0.90), 4) if valeurs else None),
            "p95": (round(_percentile(valeurs, 0.95), 4) if valeurs else None),
            "p99": (round(_percentile(valeurs, 0.99), 4) if valeurs else None),
            "max": (round(max(valeurs), 4) if valeurs else None),
            "mesure": nom,
        }

    ages = [t.source_age_ms() for t in traces]
    locales = [t.local_processing_ms() for t in traces]

    etapes: dict[str, list[float]] = {}
    for t in traces:
        for k, v in t.stage_durations_ms().items():
            etapes.setdefault(k, []).append(v)

    return {
        "evenements": total,
        # LES DEUX MESURES RESTENT SEPAREES, jusque dans le rapport.
        "age_source_ms": _stats("horloge murale (exchange -> nous) -- contient le decalage d'horloge",
                                [a for a in ages if a is not None and math.isfinite(a)]),
        "traitement_local_ms": _stats("horloge MONOTONE (reception -> decision) -- ce qu'on controle",
                                      [l for l in locales if l is not None and math.isfinite(l)]),
        "par_etape_ms": {k: _stats("horloge MONOTONE", v) for k, v in sorted(etapes.items())},
        "paper_only": True,
        "real_execution": False,
    }


__all__ = ["ETAPES", "LatencyTrace", "resumer"]

"""Collecte causale par poll REST « forward » des fills de leaders.

OBJECTIF : suivre plus de leaders que le plafond WebSocket (~10 userFills/IP de
Hyperliquid) SANS tricher. Le endpoint REST ``info/userFillsByTime`` n'est PAS
soumis au cap WS ; en l'interrogeant en continu, on observe les fills d'autres
leaders avec un ``observed_at`` honnête.

RIGUEUR — pourquoi c'est causal (et pas du backfill look-ahead) :
- Le **backfill** regarde en arrière : on tire des fills qu'on n'a jamais vus se
  former en direct -> les utiliser comme signal serait du look-ahead (interdit).
- Le **poll forward** regarde en avant : à chaque passe, on n'émet comme causal
  QUE les fills apparus DEPUIS la dernière observation, horodatés à l'instant où
  NOTRE poll les a vus. On agit après, au délai réel. Aucune information future.

Discipline anti-look-ahead, identique au WS (snapshot vs updates) :
- 1re observation d'un leader -> ses fills préexistants fixent le « high-water »
  mais ne sont JAMAIS causaux (on ne les a pas vus se former) : snapshot, exclus.
- Observations suivantes -> seuls les fills strictement nouveaux (postérieurs au
  high-water, ou de même ms mais identifiant inédit) sont causaux.

Ce module est PUR (aucune E/S réseau) : il décide quels fills sont causaux. Le
collecteur réseau l'utilise. Lecture seule, PAPER : jamais d'ordre ni de clé.
"""
from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

# Source distincte : provenance honnête (poll REST, PAS un WebSocket). Elle est
# causale au même titre que LIVE_WS *grâce à* la discipline high-water ci-dessous.
LIVE_POLL_SOURCE = "LIVE_POLL"


def _fill_identity(fill: Mapping[str, Any]) -> str | None:
    """Identité stable d'un fill pour dédupliquer à l'intérieur d'un même ms."""
    tid = fill.get("tid")
    if isinstance(tid, int) and not isinstance(tid, bool):
        return f"tid:{tid}"
    digest = fill.get("hash")
    if isinstance(digest, str) and digest.strip():
        return f"hash:{digest.strip()}"
    return None


def _fill_time_ms(fill: Mapping[str, Any]) -> int | None:
    value = fill.get("time")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


class LeaderWatermark:
    """État causal persistable par leader : dernière observation forward.

    - ``initialised`` : True dès qu'on a observé le leader au moins une fois.
    - ``high_water_ms`` : ms du fill le plus récent déjà observé.
    - ``high_water_ids`` : identités des fills exactement à ``high_water_ms``
      (pour ne pas réémettre un fill de même ms déjà vu).
    """

    __slots__ = ("initialised", "high_water_ms", "high_water_ids")

    def __init__(
        self,
        *,
        initialised: bool = False,
        high_water_ms: int = 0,
        high_water_ids: set[str] | None = None,
    ) -> None:
        self.initialised = bool(initialised)
        self.high_water_ms = int(high_water_ms)
        self.high_water_ids = set(high_water_ids or ())

    @classmethod
    def from_state(cls, state: Mapping[str, Any] | None) -> "LeaderWatermark":
        if not isinstance(state, Mapping):
            return cls()
        ids = state.get("high_water_ids")
        ids = {str(x) for x in ids} if isinstance(ids, (list, tuple, set)) else set()
        hw = state.get("high_water_ms")
        hw = int(hw) if isinstance(hw, int) and not isinstance(hw, bool) and hw > 0 else 0
        return cls(
            initialised=state.get("initialised") is True,
            high_water_ms=hw,
            high_water_ids=ids,
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "initialised": self.initialised,
            "high_water_ms": self.high_water_ms,
            "high_water_ids": sorted(self.high_water_ids),
        }


# Marge anti-straggler : le high-water avance jusqu'à (fin de fenêtre − marge),
# de sorte qu'un leader SANS fill ne garde jamais high_water=0 (ce qui le ferait
# re-tirer tout son historique au poll suivant) tout en re-couvrant la dernière
# minute pour rattraper un fill arrivé en léger différé.
_STRAGGLER_MARGIN_MS = 60_000
# Fraîcheur : un fill observé plus de N ms après son trade n'est PAS un signal de
# copie exploitable (on ne peut pas agir dessus à temps). On ne l'émet donc pas
# comme causal — cela élimine le backlog/historique ancien qui polluait le jeu.
DEFAULT_MAX_OBSERVATION_LAG_MS = 600_000  # 10 min (large : couvre poll + backoff)


def partition_forward_fills(
    watermark: LeaderWatermark,
    polled_fills: Sequence[Mapping[str, Any]],
    *,
    observed_at_ms: int,
    max_observation_lag_ms: int | None = DEFAULT_MAX_OBSERVATION_LAG_MS,
) -> tuple[list[dict[str, Any]], LeaderWatermark]:
    """Partitionne une passe de poll en fills causaux + nouveau high-water.

    Renvoie ``(causal_fills, nouveau_watermark)``. Garanties :
    - à la 1re observation (``watermark.initialised`` False), AUCUN fill causal ;
    - sinon, uniquement les fills strictement nouveaux depuis le high-water,
      chacun estampillé ``observed_at_ms`` (l'instant réel du poll), ``source``
      = ``LIVE_POLL``, ``isSnapshot`` = False ;
    - jamais un fill antérieur, déjà vu, OU observé trop tard (backlog ancien) ;
    - le high-water avance au moins jusqu'à (observed_at − marge) : aucun leader
      ne régresse vers un historique profond.
    """
    if not isinstance(observed_at_ms, int) or isinstance(observed_at_ms, bool) or observed_at_ms <= 0:
        raise ValueError("observed_at_ms doit être un entier d'epoch ms positif")

    new_hw = watermark.high_water_ms
    new_ids = set(watermark.high_water_ids)
    causal: list[dict[str, Any]] = []

    ordered = sorted(
        (f for f in polled_fills if isinstance(f, Mapping)),
        key=lambda f: (_fill_time_ms(f) or 0, _fill_identity(f) or ""),
    )
    for fill in ordered:
        ts = _fill_time_ms(fill)
        identity = _fill_identity(fill)
        if ts is None or identity is None:
            continue  # fail-closed : sans horloge/identité, jamais causal
        # Déjà couvert par le high-water : antérieur, ou même ms déjà observé.
        if ts < watermark.high_water_ms:
            continue
        if ts == watermark.high_water_ms and identity in watermark.high_water_ids:
            continue
        # Fill nouveau relativement au high-water -> met à jour le high-water.
        if ts > new_hw:
            new_hw = ts
            new_ids = {identity}
        elif ts == new_hw:
            new_ids.add(identity)
        # Gate de fraîcheur : un fill observé trop tard (backlog/historique) n'est
        # pas un signal causal exploitable -> on l'a vu (high-water avance) mais on
        # ne l'émet PAS. C'est ce qui bloque la pollution des fills vieux de jours.
        if max_observation_lag_ms is not None and (observed_at_ms - ts) > int(max_observation_lag_ms):
            continue
        # Causal UNIQUEMENT si le leader était déjà observé (sinon : préexistant).
        if watermark.initialised:
            causal.append({
                **dict(fill),
                "source": LIVE_POLL_SOURCE,
                "isSnapshot": False,
                "is_snapshot": False,
                "observed_at_ms": int(observed_at_ms),
                "received_at_ms": int(observed_at_ms),
                "observation_transport": "hyperliquid_rest_poll",
            })

    # Plancher anti-régression : le high-water ne reste jamais bloqué dans le passé
    # profond (sinon startTime=high_water re-tirerait des centaines de jours).
    floor = int(observed_at_ms) - _STRAGGLER_MARGIN_MS
    if floor > new_hw:
        new_hw = floor
        new_ids = set()

    return causal, LeaderWatermark(
        initialised=True,
        high_water_ms=new_hw,
        high_water_ids=new_ids,
    )


# Cap de réponse Hyperliquid userFillsByTime (fills par page). Au-delà, paginer.
RESPONSE_PAGE_CAP = 2_000


def shard_leaders(leaders: Sequence[str], shard_count: int, shard_index: int) -> list[str]:
    """Tranche déterministe et DISJOINTE des leaders pour une lane (IP) donnée.

    Solution #3 (scaling) : plusieurs lanes (PC + runners GitHub/cloud, IP
    distinctes) couvrent des leaders DIFFÉRENTS sans chevauchement -> le nombre
    de leaders suivis (donc de fills) croît linéairement avec le nombre de lanes.
    """
    if shard_count <= 1:
        return list(leaders)
    if not (0 <= shard_index < shard_count):
        raise ValueError("shard_index hors de [0, shard_count)")
    return [v for i, v in enumerate(leaders) if i % shard_count == shard_index]


def adaptive_interval_s(
    base_s: float, recent_fill_count: int, *, min_s: float = 2.0, max_s: float = 60.0,
) -> float:
    """Cadence de poll adaptative à l'activité du leader.

    Solution #2 : un leader qui vient d'émettre des fills est poll plus souvent
    (observed_at plus frais, moins de fills groupés) ; un leader silencieux est
    espacé (budget de requêtes libéré pour suivre PLUS de leaders). Borné.
    """
    base = max(min_s, min(max_s, float(base_s)))
    if recent_fill_count <= 0:
        return min(max_s, base * 3.0)
    if recent_fill_count >= 5:
        return max(min_s, base / 3.0)
    return base


def is_causal_live_source(source: object) -> bool:
    """Un fill est causal « live » s'il vient du WS ou du poll forward discipliné.

    Point unique de vérité partagé par les portes causales du pipeline, pour que
    ``LIVE_POLL`` soit traité exactement comme ``LIVE_WS`` — ni plus, ni moins.
    """
    return source in {"LIVE_WS", LIVE_POLL_SOURCE}


# ---------------------------------------------------------------------------
# « Plus de fills » — leviers purs et testables, branchés sur le collecteur.
# Chacun augmente le NOMBRE de fills causaux collectés par minute SANS jamais
# dépasser le plafond de requêtes Hyperliquid ni affaiblir la causalité.
# ---------------------------------------------------------------------------


class TokenBucket:
    """#1 Limiteur à jetons — débit soutenu ``rate_per_s`` avec rafales jusqu'à
    ``burst``. Il MAXIMISE le nombre de requêtes sous le plafond HL (donc plus de
    fills/min qu'un espacement fixe), tout en absorbant les creux sans jamais le
    franchir. Horloge/sommeil injectables -> déterministe en test."""

    def __init__(
        self, rate_per_s: float, burst: float, *, now=None, sleep=None,
        penalty_base_s: float = 10.0, penalty_max_s: float = 300.0,
    ) -> None:
        self.rate = max(1e-6, float(rate_per_s))
        self.burst = max(1.0, float(burst))
        self._now = now or time.monotonic
        self._sleep = sleep or time.sleep
        self._tokens = self.burst
        self._last = self._now()
        # Coupe-circuit GLOBAL anti-429 : le 429 d'Hyperliquid est au niveau de
        # l'IP entiere, donc on met TOUT le poll en pause (pas un seul leader).
        self.penalty_base_s = max(0.0, float(penalty_base_s))
        self.penalty_max_s = max(self.penalty_base_s, float(penalty_max_s))
        self._pause_until = 0.0
        self._cooldown_s = 0.0

    def _refill(self) -> None:
        t = self._now()
        self._tokens = min(self.burst, self._tokens + max(0.0, t - self._last) * self.rate)
        self._last = t

    def penalize(self) -> None:
        """429 observe : pause globale croissante (exponentielle, bornee)."""
        self._cooldown_s = min(
            self.penalty_max_s,
            max(self.penalty_base_s, self._cooldown_s * 2.0),
        )
        self._pause_until = self._now() + self._cooldown_s

    def reward(self) -> None:
        """Requete reussie : on relache progressivement la pause globale."""
        self._cooldown_s = max(0.0, self._cooldown_s / 2.0)

    def take(self) -> float:
        """Consomme un jeton (attend si nécessaire). Renvoie le temps attendu (s)."""
        waited = 0.0
        now = self._now()
        if now < self._pause_until:              # pause globale active (429)
            waited += self._pause_until - now
            self._sleep(waited)
        self._refill()
        if self._tokens < 1.0:
            extra = (1.0 - self._tokens) / self.rate
            self._sleep(extra)
            waited += extra
            self._refill()
        self._tokens = max(0.0, self._tokens - 1.0)
        return waited


def prioritize_leaders(
    leaders: Sequence[str], retained: Sequence[str] | None,
) -> list[str]:
    """#2 Priorisation par valeur — met les leaders retenus/scorés EN PREMIER (sans
    doublon, ordre stable). Le budget de requêtes frappe d'abord les leaders les
    plus productifs -> plus de fills causaux par minute pour un même budget."""
    retained_set = {str(r).lower() for r in (retained or [])}
    ordered = [v for v in leaders if str(v).lower() in retained_set]
    ordered += [v for v in leaders if str(v).lower() not in retained_set]
    seen: set[str] = set()
    out: list[str] = []
    for v in ordered:
        k = str(v).lower()
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


class LeaderCooldown:
    """#3 Backoff par leader — après un 429/erreur sur UN leader, on le met en
    pause (exponentielle bornée) pour ne pas gaspiller le budget dessus ; les
    autres continuent d'être pollés. Un succès réarme le leader. Résultat : plus
    de fills utiles au total, zéro tempête de 429 sur un leader fautif."""

    def __init__(self, base_ms: float = 5_000.0, max_ms: float = 300_000.0) -> None:
        self.base_ms = max(0.0, float(base_ms))
        self.max_ms = max(self.base_ms, float(max_ms))
        self._until: dict[str, float] = {}
        self._streak: dict[str, int] = {}

    def penalize(self, vault: str, now_ms: float) -> None:
        n = self._streak.get(vault, 0) + 1
        self._streak[vault] = n
        self._until[vault] = now_ms + min(self.max_ms, self.base_ms * (2 ** (n - 1)))

    def reset(self, vault: str) -> None:
        self._streak.pop(vault, None)
        self._until.pop(vault, None)

    def due(self, vault: str, now_ms: float) -> bool:
        return now_ms >= self._until.get(vault, 0.0)


def merge_dedup_fills(*streams: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """#4 Fusion WS+poll — réunit plusieurs flux de fills en dédupliquant par
    identité source-indépendante ``(vault,coin,time,tid/hash,oid,px,sz,side)`` et
    en PRÉFÉRANT l'observation causale non-snapshot. Garantit qu'un même trade vu
    par le WS et par le poll ne compte qu'une fois (aucune donnée double)."""
    best: dict[tuple, dict[str, Any]] = {}
    for stream in streams:
        for f in stream:
            if not isinstance(f, Mapping):
                continue
            key = (
                f.get("vault"), f.get("coin"), f.get("time"), _fill_identity(f),
                f.get("oid"), f.get("px"), f.get("sz"), f.get("side"),
            )
            prev = best.get(key)
            if prev is None:
                best[key] = dict(f)
            elif prev.get("isSnapshot") and not f.get("isSnapshot"):
                best[key] = dict(f)  # préfère la vue causale non-snapshot
    return list(best.values())


def collector_stream_health(
    mtime_ms: float | None, now_ms: float, *, expected_interval_ms: float,
) -> str:
    """#5 Santé d'un flux — verdict de fraîcheur : ``ABSENT`` (jamais écrit),
    ``FRESH`` (écrit récemment), ``STALE`` (en retard), ``DEAD`` (figé depuis
    longtemps). Base de la page de santé des collecteurs (répond à « ça monte ? »)."""
    if not mtime_ms or mtime_ms <= 0:
        return "ABSENT"
    age = now_ms - mtime_ms
    if age <= max(1.0, expected_interval_ms):
        return "FRESH"
    if age <= expected_interval_ms * 10.0:
        return "STALE"
    return "DEAD"


__all__ = [
    "LIVE_POLL_SOURCE",
    "RESPONSE_PAGE_CAP",
    "LeaderWatermark",
    "partition_forward_fills",
    "shard_leaders",
    "adaptive_interval_s",
    "is_causal_live_source",
    "TokenBucket",
    "prioritize_leaders",
    "LeaderCooldown",
    "merge_dedup_fills",
    "collector_stream_health",
]

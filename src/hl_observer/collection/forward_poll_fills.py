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


def partition_forward_fills(
    watermark: LeaderWatermark,
    polled_fills: Sequence[Mapping[str, Any]],
    *,
    observed_at_ms: int,
) -> tuple[list[dict[str, Any]], LeaderWatermark]:
    """Partitionne une passe de poll en fills causaux + nouveau high-water.

    Renvoie ``(causal_fills, nouveau_watermark)``. Garanties :
    - à la 1re observation (``watermark.initialised`` False), AUCUN fill causal ;
    - sinon, uniquement les fills strictement nouveaux depuis le high-water,
      chacun estampillé ``observed_at_ms`` (l'instant réel du poll), ``source``
      = ``LIVE_POLL``, ``isSnapshot`` = False ;
    - jamais un fill antérieur ou déjà vu.
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


__all__ = [
    "LIVE_POLL_SOURCE",
    "RESPONSE_PAGE_CAP",
    "LeaderWatermark",
    "partition_forward_fills",
    "shard_leaders",
    "adaptive_interval_s",
    "is_causal_live_source",
]

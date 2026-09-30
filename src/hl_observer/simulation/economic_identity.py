"""P1C — identité économique bout-en-bout, portée par `PaperEvent.refs` (aucune rupture de hash-chain).

Aujourd'hui `PaperEvent` porte `session_id` + les champs de chaîne en première classe ; les identités
plus riches (strategy, intent_id, plan_id, position_id, execution_snapshot_id) voyagent déjà dans le
dict libre `refs`, et **`episode_id` n'existe nulle part**. Chaque événement économique doit pouvoir
répondre : quelle stratégie, quelle session, quel intent, quel plan, quelle position, quel épisode,
quel event source, quel snapshot d'exécution — et OPEN/ADD/REDUCE/CLOSE/FLIP doivent pointer vers la
bonne exposition, **jamais** une clé ambiguë `(coin, side)` si une identité existe.

Ce module fournit ce bundle typé, sérialisable dans `refs` (seuls les champs présents sont émis, donc
fusion propre), reconstructible, et deux clés stables : `position_key()` (position_id sinon `COIN:SIDE`,
miroir de `PaperLedger._position_key`) et `episode_key()` (episode_id sinon la position). Générateur
d'`episode_id` **déterministe** (pas d'horloge : replay = forward). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from hashlib import sha256
from typing import Any, Mapping

SCHEMA_VERSION = "hypersmart.economic_identity.v1"

#: Champs d'identité, dans l'ordre causal (décision → exécution → comptabilité).
_CHAMPS = (
    "strategy", "session_id", "intent_id", "plan_id", "position_id", "episode_id",
    "source_event_id", "execution_snapshot_id", "wallet_id", "entity_id",
    "coin", "venue", "side", "action",
)


def _norm(v: Any) -> str | None:
    if v in (None, ""):
        return None
    return str(v)


@dataclass(frozen=True, slots=True)
class EconomicIdentity:
    strategy: str | None = None
    session_id: str | None = None
    intent_id: str | None = None
    plan_id: str | None = None
    position_id: str | None = None
    episode_id: str | None = None
    source_event_id: str | None = None
    execution_snapshot_id: str | None = None
    wallet_id: str | None = None
    entity_id: str | None = None
    coin: str | None = None
    venue: str | None = None
    side: str | None = None
    action: str | None = None

    def to_refs(self) -> dict[str, str]:
        """Sous-dict à fusionner dans `PaperEvent.refs` : SEULS les champs présents (fusion non destructive)."""
        out: dict[str, str] = {}
        for c in _CHAMPS:
            v = _norm(getattr(self, c))
            if v is not None:
                out[c] = v
        return out

    @classmethod
    def from_refs(cls, refs: Mapping[str, Any] | None) -> "EconomicIdentity":
        r = refs or {}
        return cls(**{c: _norm(r.get(c)) for c in _CHAMPS})

    def position_key(self) -> str | None:
        """Clé de position : `position_id` si présent, sinon `COIN:SIDE`. `None` si même le repli manque."""
        if self.position_id:
            return str(self.position_id)
        if self.coin and self.side:
            return f"{str(self.coin).upper()}:{str(self.side).upper()}"
        return None

    def episode_key(self) -> str | None:
        """Clé d'épisode : `episode_id` si présent, sinon la position (un épisode = une exposition close)."""
        if self.episode_id:
            return str(self.episode_id)
        return self.position_key()

    def missing(self) -> tuple[str, ...]:
        """Champs d'identité absents — pour rendre les trous VISIBLES au lieu de les masquer."""
        return tuple(c for c in _CHAMPS if _norm(getattr(self, c)) is None)

    def with_fields(self, **kw: Any) -> "EconomicIdentity":
        from dataclasses import replace
        return replace(self, **kw)


def nouvel_episode_id(
    *, session_id: object, strategy: object, coin: object, side: object, ouverture_ref: object
) -> str:
    """`episode_id` DÉTERMINISTE (aucune horloge) : même ouverture ⇒ même id en replay et en forward.

    `ouverture_ref` = repère stable de l'ouverture (intent_id, event_id d'OPEN, ou seq). Deux épisodes
    distincts sur le même coin/side ne collisionnent pas tant que leur `ouverture_ref` diffère."""
    material = "|".join(str(x) for x in (session_id, strategy, coin, side, ouverture_ref))
    return "E:" + sha256(material.encode("utf-8")).hexdigest()[:20]


def stamp_refs(refs: Mapping[str, Any] | None, identity: EconomicIdentity) -> dict[str, Any]:
    """Fusionne l'identité dans un `refs` existant sans écraser une valeur déjà présente et non vide."""
    out = dict(refs or {})
    for k, v in identity.to_refs().items():
        if out.get(k) in (None, ""):
            out[k] = v
    return out


__all__ = [
    "SCHEMA_VERSION", "EconomicIdentity", "nouvel_episode_id", "stamp_refs",
]

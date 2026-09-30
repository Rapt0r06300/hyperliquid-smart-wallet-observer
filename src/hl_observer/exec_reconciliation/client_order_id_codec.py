"""[EXEC pépite 213] DETERMINISTIC CLIENT-ORDER-ID CODEC : encoder module + episode + leg + generation dans
l'identifiant client (déterministe et RÉVERSIBLE). Un client-order-id qui porte sa provenance permet de réconcilier
un fill orphelin à son intention sans table externe, et de re-dériver le même id à l'identique en cas de retry.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_SEP = "-"


def encoder(*, module: str, episode: Any, leg: Any, generation: Any) -> str:
    """Assemble un client-order-id déterministe. Les champs sont normalisés (majuscules module) et joints par '-'."""
    return _SEP.join([str(module).upper(), str(episode), str(leg), str(generation)])


def decoder(client_order_id: Any) -> dict[str, Any]:
    """Ré-extrait {module, episode, leg, generation} d'un client-order-id. Format invalide → non décodable."""
    parts = str(client_order_id).split(_SEP)
    if len(parts) != 4:
        return {"ok": False, "raison": "FORMAT_INVALIDE"}
    return {"ok": True, "module": parts[0], "episode": parts[1], "leg": parts[2], "generation": parts[3]}


def roundtrip_stable(*, module: str, episode: Any, leg: Any, generation: Any) -> bool:
    """Encoder puis décoder redonne les mêmes champs (déterminisme vérifié)."""
    cid = encoder(module=module, episode=episode, leg=leg, generation=generation)
    d = decoder(cid)
    return bool(d["ok"] and d["module"] == str(module).upper() and d["episode"] == str(episode)
               and d["leg"] == str(leg) and d["generation"] == str(generation))


__all__ = ["encoder", "decoder", "roundtrip_stable"]

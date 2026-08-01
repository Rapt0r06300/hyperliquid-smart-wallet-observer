"""[COPY-VAULT pépite 280] SOURCE MAKER/TAKER CLASSIFIER : séparer les fills du leader qui ont FOURNI la
liquidité (maker, ordre au repos exécuté) de ceux qui l'ont PRISE (taker, ordre agressif qui croise le spread).
La distinction est cruciale pour la copyabilité : un edge obtenu en maker (rebate, pas de franchissement de
spread) n'est pas reproductible tel quel en taker. Aucun signal fiable → UNMEASURABLE. Pur, 0 réseau, 0 ordre
réel.
"""
from __future__ import annotations

from typing import Any

MAKER = "MAKER"
TAKER = "TAKER"
UNMEASURABLE = "UNMEASURABLE"


def classer(fill: dict[str, Any]) -> dict[str, Any]:
    """Priorité des signaux : is_maker explicite, sinon liquidity (M/T), sinon crossed (Hyperliquid : crossed
    True = a croisé le spread = taker). Aucun de ces champs → UNMEASURABLE (on ne devine pas le rôle)."""
    if not isinstance(fill, dict):
        return {"classe": UNMEASURABLE, "raison": "FILL_INVALIDE"}
    if isinstance(fill.get("is_maker"), bool):
        return {"classe": MAKER if fill["is_maker"] else TAKER, "source": "is_maker"}
    liq = str(fill.get("liquidity", "")).upper()
    if liq in ("M", "MAKER"):
        return {"classe": MAKER, "source": "liquidity"}
    if liq in ("T", "TAKER"):
        return {"classe": TAKER, "source": "liquidity"}
    if isinstance(fill.get("crossed"), bool):
        return {"classe": TAKER if fill["crossed"] else MAKER, "source": "crossed"}
    return {"classe": UNMEASURABLE, "raison": "AUCUN_SIGNAL_LIQUIDITE"}


__all__ = ["classer", "MAKER", "TAKER", "UNMEASURABLE"]

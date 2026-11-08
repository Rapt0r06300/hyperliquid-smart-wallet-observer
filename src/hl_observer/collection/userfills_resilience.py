"""Lot 2 — Resilience anti-perte du flux userFills (PUR, testable, 0 reseau).

Deux garanties pour ne perdre AUCUN fill live (chaque fill = un jour potentiellement
scoreable par le labo) :

1. **Gap-fill au reconnect** : apres une coupure WS, on calcule la fenetre temporelle
   a rattraper par poll REST ``userFillsByTime`` pour chaque user, bornee (jamais des
   mois d'historique), avec une petite marge de recouvrement (zero trou a la jointure).
2. **Deduplication** WS <-> poll <-> reconnect par identite stable du fill, avec un
   cache borne (LRU) pour ne pas gonfler la memoire sur un long run.

Deterministe. Reutilise l'identite de fill alignee sur le labo/coffre (tid/hash/oid +
vault/coin/ts/px/sz/signe) pour que WS et poll se dedupliquent mutuellement.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

#: borne dure du rattrapage : jamais rejouer plus de 1 h (sinon on ne fait pas du
#: forward causal mais de l'historique, qui n'est pas emis comme causal).
MAX_GAPFILL_LOOKBACK_MS = 3_600_000
#: marge de recouvrement a la jointure WS/poll (on re-demande un peu avant le
#: high-water pour ne rien perdre ; les doublons sont filtres par la dedup).
GAPFILL_MARGE_MS = 2_000


def fenetre_gapfill(
    high_water_ms: int | None, now_ms: int, *,
    marge_ms: int = GAPFILL_MARGE_MS, max_lookback_ms: int = MAX_GAPFILL_LOOKBACK_MS,
) -> tuple[int, int] | None:
    """Fenetre (start_ms, end_ms) a rattraper par poll apres un reconnect WS.

    - ``high_water_ms`` = ts du dernier fill vu avant la coupure (None = pas d'historique
      fiable -> on rattrape au plus ``max_lookback_ms``, sans jamais aller plus loin).
    - recouvrement : on recule de ``marge_ms`` avant le high-water (dedup ensuite).
    - borne dure : start ne descend jamais sous ``now - max_lookback_ms``.
    Renvoie None si rien a rattraper (fenetre vide).
    """
    now_ms = int(now_ms)
    plancher = max(1, now_ms - int(max_lookback_ms))
    if high_water_ms and high_water_ms > 0:
        start = max(plancher, int(high_water_ms) - int(marge_ms))
    else:
        start = plancher
    end = now_ms
    if start >= end:
        return None
    return start, end


def cle_dedup_fill(fill: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identite stable d'un fill pour la deduplication inter-source/inter-reconnect.

    Alignee sur l'identite du labo/coffre : on privilegie les identifiants d'echange
    (tid/hash/oid) ; a defaut on retombe sur (vault, coin, ts, px, sz, signe).
    """
    if not isinstance(fill, Mapping):
        return ("?", repr(fill)[:64])
    vault = str(fill.get("vault") or "").lower()
    coin = str(fill.get("coin") or "")
    ts = fill.get("ts_ms")
    if ts is None:
        ts = fill.get("time")
    return (
        vault, coin, ts,
        fill.get("tid"), fill.get("hash"), fill.get("oid"),
        fill.get("px"), fill.get("sz"), fill.get("signe"),
    )


class DedupFills:
    """Cache borne (LRU) d'identites de fills deja emis.

    ``vu_ou_marquer(fill)`` renvoie True si deja vu (a ignorer), False si nouveau (et
    le marque). Capacite bornee : au-dela, on oublie les plus anciens (les vieux fills
    ne reviennent pas une fois le high-water passe, donc sans risque de re-emission).
    """

    def __init__(self, capacite: int = 200_000) -> None:
        self.capacite = max(1, int(capacite))
        self._vus: "OrderedDict[tuple[Any, ...], None]" = OrderedDict()

    def __len__(self) -> int:
        return len(self._vus)

    def vu_ou_marquer(self, fill: Mapping[str, Any]) -> bool:
        cle = cle_dedup_fill(fill)
        if cle in self._vus:
            self._vus.move_to_end(cle)
            return True
        self._vus[cle] = None
        if len(self._vus) > self.capacite:
            self._vus.popitem(last=False)
        return False

    def filtrer_nouveaux(self, fills) -> list[dict[str, Any]]:
        """Renvoie, dans l'ordre, les fills NON encore vus (et les marque)."""
        sortie: list[dict[str, Any]] = []
        for f in fills or ():
            if isinstance(f, Mapping) and not self.vu_ou_marquer(f):
                sortie.append(dict(f))
        return sortie


__all__ = [
    "MAX_GAPFILL_LOOKBACK_MS", "GAPFILL_MARGE_MS",
    "fenetre_gapfill", "cle_dedup_fill", "DedupFills",
]

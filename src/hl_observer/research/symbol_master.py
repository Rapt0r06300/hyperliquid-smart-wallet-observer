"""[AUD-279/280] Symbol master (normalisation des symboles cross-venue vers un canonique unique) et
horloge MULTI-VENUE (offsets par rapport a une reference, skew maximal). Sans master, deux 'BTC' de
deux venues peuvent designer des contrats differents ; sans horloge alignee, l'ordre des evenements
cross-venue est faux. stdlib pure, 0 reseau."""
from __future__ import annotations

from typing import Mapping


class SymbolMaster:
    """Referentiel CANONIQUE : (binance, BTCUSDT) / (coinbase, BTC-USD) / (hl, BTC) -> 'BTC'."""

    def __init__(self) -> None:
        self._map: dict[tuple, str] = {}

    def enregistrer(self, venue: str, symbole_venue: str, canonique: str) -> None:
        self._map[(venue, symbole_venue)] = canonique

    def resoudre(self, venue: str, symbole_venue: str) -> str | None:
        return self._map.get((venue, symbole_venue))

    def venues_pour(self, canonique: str) -> list[str]:
        return sorted({v for (v, _s), c in self._map.items() if c == canonique})


def aligner_horloges(ts_par_venue: Mapping[str, float], *, reference: str | None = None) -> dict:
    """Horloge MULTI-VENUE : offset de chaque venue vs une reference (defaut : la plus en avance) +
    skew maximal. Un skew non corrige fausse tout lead-lag cross-venue."""
    if not ts_par_venue:
        return {"reference": None, "offsets": {}, "skew_max": 0.0}
    ref = reference or max(ts_par_venue, key=lambda v: ts_par_venue[v])
    ref_ts = ts_par_venue[ref]
    offsets = {v: ts_par_venue[v] - ref_ts for v in ts_par_venue}
    skew = max(offsets.values()) - min(offsets.values())
    return {"reference": ref, "offsets": offsets, "skew_max": skew}

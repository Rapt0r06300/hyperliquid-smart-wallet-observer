"""PALIER DE FRAIS AU VOLUME (idée #13) — les frais Hyperliquid baissent avec le volume 14 j. Un
palier plus bas = coût d'entrée plus faible = carry plus rentable. Deny-by-default : on n'assume
QUE le palier que le compte atteint RÉELLEMENT (volume mesuré). PAPER only, aucun ordre.

Table indicative (bps par jambe ; à confronter à la doc officielle via fees/hyperliquid_fees) :
    volume 14 j < 5 M$    : maker 1.5 / taker 4.5
    >= 5 M$               : maker 1.2 / taker 4.0
    >= 25 M$              : maker 1.0 / taker 3.5
"""
from __future__ import annotations

# (seuil_volume_usd, maker_bps, taker_bps), du plus haut volume au plus bas.
PALIERS = (
    (25_000_000.0, 1.0, 3.5),
    (5_000_000.0, 1.2, 4.0),
    (0.0, 1.5, 4.5),
)


def frais_selon_volume(volume_14j_usd: float | None) -> tuple[float, float]:
    """(maker_bps, taker_bps) pour le volume atteint. Volume inconnu/négatif -> palier de BASE
    (le plus cher) : on ne suppose JAMAIS un meilleur palier qu'on n'a pas prouvé."""
    v = float(volume_14j_usd) if isinstance(volume_14j_usd, (int, float)) and volume_14j_usd > 0 else 0.0
    for seuil, maker, taker in PALIERS:
        if v >= seuil:
            return maker, taker
    return PALIERS[-1][1], PALIERS[-1][2]


def economie_bps_2_jambes(volume_14j_usd: float | None, *, maker: bool = True) -> float:
    """Économie (bps) sur les 2 jambes vs le palier de base, grâce au volume. >= 0."""
    base_m, base_t = PALIERS[-1][1], PALIERS[-1][2]
    m, t = frais_selon_volume(volume_14j_usd)
    return round(2.0 * ((base_m - m) if maker else (base_t - t)), 4)


__all__ = ["frais_selon_volume", "economie_bps_2_jambes", "PALIERS"]

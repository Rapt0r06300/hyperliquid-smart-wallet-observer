"""EXPLOITER le funding cross-venue (pas seulement le mesurer) — cycle de vie d'une position PAPER
delta-neutre entre deux venues : ouvrir, accruer le funding capté, sortir, PnL réalisé.

On est LONG le perp où le funding est le plus BAS et SHORT là où il est le plus HAUT, même coin ->
exposition prix ~annulée ; on encaisse l'écart |f_haut - f_bas| par heure. Deny-by-default :
dispersion disparue -> on SORT (le funding ne paie plus). Coûts d'entrée ET de sortie comptés.
PAPER only : aucun ordre, aucune clé, aucune venue n'est contactée pour agir — Hyperliquid reste
la seule venue des décisions, la 2e venue n'est qu'une SOURCE DE PRIX en lecture.
"""
from __future__ import annotations

from typing import Any

COUT_ENTREE_2_JAMBES_BPS = 11.0
COUT_SORTIE_2_JAMBES_BPS = 11.0
DISPERSION_MIN_TENUE_BPS_H = 0.02     # sous ça, la dispersion a disparu -> on sort
AGE_MAX_H = 336.0                      # 14 j : au-delà, on referme et on re-decide


def ouvrir(opportunite: dict[str, Any], *, notional_usd: float, now_ms: int,
           cout_entree_bps: float = COUT_ENTREE_2_JAMBES_BPS) -> dict[str, Any] | None:
    """Matérialise une position cross-venue depuis une opportunité (cf. multi_venue_funding).
    None si l'opportunité est incomplète (on n'invente pas une jambe)."""
    coin = str(opportunite.get("coin") or "").upper()
    lv, sv = opportunite.get("long_venue"), opportunite.get("short_venue")
    cap = opportunite.get("capture_bps_h")
    if not coin or not lv or not sv or not isinstance(cap, (int, float)) or float(cap) <= 0:
        return None
    n = max(0.0, float(notional_usd))
    if n <= 0:
        return None
    return {"coin": coin, "long_venue": str(lv), "short_venue": str(sv),
            "notional_usdt": round(n, 6), "capture_bps_h_entree": round(float(cap), 6),
            "cout_entree_bps": float(cout_entree_bps), "entry_ts_ms": int(now_ms),
            "last_accrual_ts_ms": int(now_ms), "funding_accru_usdt": 0.0,
            "paper_only": True, "real_execution": False}


def accruer(position: dict[str, Any], capture_courante_bps_h: float | None, *, now_ms: int) -> float:
    """Accrue le funding capté depuis le dernier tick, au taux COURANT (pas celui d'entrée : le
    marché a pu bouger). Capture inconnue -> on n'accrue RIEN (jamais de gain inventé)."""
    if capture_courante_bps_h is None:
        return 0.0
    _last = position.get("last_accrual_ts_ms")          # 0 est un ts VALIDE : ne pas utiliser `or`
    _last = int(_last) if isinstance(_last, (int, float)) else int(now_ms)
    dt_h = max(0.0, (int(now_ms) - _last) / 3_600_000.0)
    gain = float(position["notional_usdt"]) * abs(float(capture_courante_bps_h)) / 1e4 * dt_h
    position["funding_accru_usdt"] = round(float(position.get("funding_accru_usdt") or 0.0) + gain, 8)
    position["last_accrual_ts_ms"] = int(now_ms)
    return round(gain, 8)


def raison_de_sortie(position: dict[str, Any], capture_courante_bps_h: float | None, *,
                     now_ms: int, dispersion_min: float = DISPERSION_MIN_TENUE_BPS_H,
                     age_max_h: float = AGE_MAX_H) -> str | None:
    """Pourquoi fermer ? None = on tient. La dispersion qui s'évapore est LA raison n°1."""
    _entry = position.get("entry_ts_ms")               # idem : 0 est valide
    _entry = int(_entry) if isinstance(_entry, (int, float)) else int(now_ms)
    age_h = (int(now_ms) - _entry) / 3_600_000.0
    if capture_courante_bps_h is None:
        return "SORTIE_CAPTURE_INCONNUE"          # source perdue -> on ne tient pas à l'aveugle
    if abs(float(capture_courante_bps_h)) < float(dispersion_min):
        return "SORTIE_DISPERSION_DISPARUE"
    if age_h >= float(age_max_h):
        return "SORTIE_AGE"
    return None


def pnl_realise(position: dict[str, Any], *, cout_sortie_bps: float = COUT_SORTIE_2_JAMBES_BPS) -> float:
    """PnL net = funding accru − coût d'entrée − coût de sortie. Honnête : les 2 coûts sont comptés."""
    n = float(position["notional_usdt"])
    couts = n * (float(position.get("cout_entree_bps") or 0.0) + float(cout_sortie_bps)) / 1e4
    return round(float(position.get("funding_accru_usdt") or 0.0) - couts, 8)


def break_even_heures(position: dict[str, Any], *, cout_sortie_bps: float = COUT_SORTIE_2_JAMBES_BPS) -> float | None:
    """Heures nécessaires pour rembourser entrée+sortie au taux d'entrée. None si capture nulle."""
    cap = float(position.get("capture_bps_h_entree") or 0.0)
    if cap <= 0:
        return None
    return round((float(position.get("cout_entree_bps") or 0.0) + float(cout_sortie_bps)) / cap, 2)


__all__ = ["ouvrir", "accruer", "raison_de_sortie", "pnl_realise", "break_even_heures",
           "COUT_ENTREE_2_JAMBES_BPS", "COUT_SORTIE_2_JAMBES_BPS", "DISPERSION_MIN_TENUE_BPS_H"]

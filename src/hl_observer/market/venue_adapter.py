"""ADAPTATEUR DE VENUE — funding public d'une 2e venue (Binance/Bybit) en LECTURE SEULE, pour
comparer avec Hyperliquid et alimenter l'arb cross-venue. AUCUNE exécution, AUCUNE clé, AUCUN
ordre : on ne LIT que le taux de funding public. Hyperliquid reste la seule venue des décisions.

⚠️ PIÈGE D'UNITÉ (V4) : Binance & Bybit publient le funding par **8 heures** ; Hyperliquid par
**heure**. On ramène TOUT en **bps/h** avant toute comparaison, sinon l'arb serait faux d'un
facteur 8. Les parseurs ci-dessous font la conversion, et sont testés hors réseau (le fetch, lui,
ne tourne que sous Windows — le sandbox n'a pas de réseau).
"""
from __future__ import annotations

from dataclasses import dataclass

BINANCE_FUNDING_PERIODE_H = 8.0     # fundingRate Binance = fraction par 8 h
BYBIT_FUNDING_PERIODE_H = 8.0       # idem Bybit (par défaut)


@dataclass(frozen=True)
class FundingVenue:
    venue: str
    coin: str
    funding_bps_h: float | None      # TOUJOURS en bps/heure (unité commune)
    source: str = ""

    def as_dict(self) -> dict:
        return {"venue": self.venue, "coin": self.coin, "funding_bps_h": self.funding_bps_h,
                "source": self.source, "real_execution": False}


def _fraction_8h_vers_bps_h(fraction_8h, *, periode_h: float) -> float | None:
    """fundingRate (fraction sur `periode_h`) -> bps/heure. Non numérique -> None (on ne devine pas)."""
    if not isinstance(fraction_8h, (int, float)):
        try:
            fraction_8h = float(fraction_8h)
        except (TypeError, ValueError):
            return None
    return round(float(fraction_8h) * 10_000.0 / float(periode_h), 6)


def parse_binance_premium_index(payload: dict, coin: str) -> FundingVenue:
    """Réponse Binance /fapi/v1/premiumIndex : {'lastFundingRate': '0.0001', ...} (par 8 h)."""
    rate = (payload or {}).get("lastFundingRate")
    return FundingVenue("Binance", str(coin).upper(),
                        _fraction_8h_vers_bps_h(rate, periode_h=BINANCE_FUNDING_PERIODE_H),
                        source="binance:premiumIndex")


def parse_bybit_funding(payload: dict, coin: str) -> FundingVenue:
    """Réponse Bybit /v5/market/tickers : {'result':{'list':[{'fundingRate':'0.0001'}]}} (par 8 h)."""
    try:
        rate = payload["result"]["list"][0]["fundingRate"]
    except (KeyError, IndexError, TypeError):
        rate = None
    return FundingVenue("Bybit", str(coin).upper(),
                        _fraction_8h_vers_bps_h(rate, periode_h=BYBIT_FUNDING_PERIODE_H),
                        source="bybit:tickers")


def fetch_binance_funding(coin: str, *, timeout_s: float = 6.0) -> FundingVenue:  # pragma: no cover
    """LECTURE SEULE, réseau (Windows uniquement — pas de réseau en sandbox). Public, aucune clé.
    Best-effort : erreur réseau -> funding None (on ne bloque pas, on signale l'absence)."""
    import json
    import urllib.request
    sym = str(coin).upper() + "USDT"
    url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=" + sym
    try:
        with urllib.request.urlopen(url, timeout=float(timeout_s)) as r:   # noqa: S310 (public GET)
            return parse_binance_premium_index(json.loads(r.read().decode("utf-8")), coin)
    except Exception:  # noqa: BLE001
        return FundingVenue("Binance", str(coin).upper(), None, source="binance:erreur")


__all__ = ["FundingVenue", "parse_binance_premium_index", "parse_bybit_funding",
           "fetch_binance_funding", "BINANCE_FUNDING_PERIODE_H", "BYBIT_FUNDING_PERIODE_H"]

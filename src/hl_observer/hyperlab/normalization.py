"""[Bloc 34-35 / AUD-341,342,343,344,345,346,347] Versioning point-in-time des specs de contrats +
normalisation cross-venue.

- SymbolMasterPiT : versions datees (tick, lot, multiplicateur, type lineaire/inverse) ; lookup a une
  date renvoie la version EFFECTIVE a cette date (jamais une spec future).
- normalize_ts (ms/s/iso -> epoch s), funding_to_8h (rate,intervalle_h), oi_to_notional,
  liquidation_side_position (convention par venue), quote_class + depeg, inverse_contract_notional.
Un champ manquant reste None (jamais invente). deterministe, 0 reseau."""
from __future__ import annotations

from typing import Optional


class SymbolMasterPiT:
    """Registre point-in-time des specs. get(symbole, at_ts) -> version effective la plus recente <= at_ts."""

    def __init__(self) -> None:
        self._v: dict = {}

    def ajouter_version(self, symbole: str, *, effective_ts: float, tick: float, lot: float,
                        multiplicateur: float = 1.0, type_contrat: str = "lineaire") -> None:
        assert type_contrat in ("lineaire", "inverse")
        self._v.setdefault(symbole, []).append(
            {"effective_ts": float(effective_ts), "tick": tick, "lot": lot,
             "multiplicateur": multiplicateur, "type_contrat": type_contrat})
        self._v[symbole].sort(key=lambda x: x["effective_ts"])

    def get(self, symbole: str, at_ts: float) -> Optional[dict]:
        versions = self._v.get(symbole, [])
        eff = [v for v in versions if v["effective_ts"] <= at_ts]
        return dict(eff[-1]) if eff else None


def normalize_ts(v) -> Optional[float]:
    """ms / s / ISO -> epoch secondes (float). Inconnu -> None."""
    if v is None:
        return None
    try:
        if isinstance(v, str):
            s = v.strip()
            if len(s) >= 19 and s[4] == "-" and s[7] == "-":
                import datetime as _dt
                return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
            v = float(s)
        v = float(v)
        return v / 1000.0 if v > 1e12 else v
    except (TypeError, ValueError):
        return None


def funding_to_8h(rate: float, intervalle_h: float) -> Optional[float]:
    """Normalise un funding rate a une base 8h (AUD-344). intervalle_h=1 -> *8, =8 -> *1."""
    try:
        if intervalle_h <= 0:
            return None
        return float(rate) * (8.0 / float(intervalle_h))
    except (TypeError, ValueError):
        return None


def oi_to_notional(oi_contrats: float, multiplicateur: float, prix: float) -> Optional[float]:
    """Open interest en contrats -> notionnel USD (AUD-345). Un facteur manquant -> None."""
    try:
        if oi_contrats is None or multiplicateur is None or prix is None:
            return None
        return float(oi_contrats) * float(multiplicateur) * float(prix)
    except (TypeError, ValueError):
        return None


_LIQ_CONV = {  # convention: le champ 'side' de la venue designe-t-il l'ordre de liq (aggressor) ?
    "bybit": "aggressor", "okx": "aggressor", "binance": "aggressor",
    "kraken": "aggressor", "deribit": "aggressor",
}


def liquidation_side_position(venue: str, raw_side: str) -> Optional[str]:
    """Normalise vers le sens de la POSITION liquidee (AUD-346). Si la venue donne l'ordre aggressor,
    la position liquidee est l'oppose : un ordre de liquidation 'sell' solde une position 'long'."""
    s = str(raw_side).strip().lower()
    base = "buy" if s in ("buy", "b", "bid", "long") else ("sell" if s in ("sell", "s", "ask", "short") else None)
    if base is None:
        return None
    if _LIQ_CONV.get(venue, "aggressor") == "aggressor":
        return "long" if base == "sell" else "short"
    return "long" if base == "buy" else "short"


_STABLES = {"USD": "usd", "USDT": "usdt", "USDC": "usdc"}


def quote_class(quote: str, *, prix_vs_usd: Optional[float] = None, seuil_depeg: float = 0.01) -> dict:
    """Classe la devise de cotation (USD/USDT/USDC) et signale un depeg si prix_vs_usd s'ecarte (AUD-343)."""
    q = str(quote).upper()
    cls = _STABLES.get(q)
    depeg = None
    if prix_vs_usd is not None:
        depeg = abs(float(prix_vs_usd) - 1.0) > seuil_depeg
    return {"quote": q, "classe": cls, "stable": cls is not None, "depeg": depeg}


def inverse_contract_notional(qty_contrats: float, contrat_usd: float, prix: float) -> Optional[float]:
    """Contrat INVERSE (ex BTC-USD coin-margined) : notionnel USD = qty * contrat_usd (taille fixe en
    USD) ; l'exposition en coin = notionnel/prix. Un facteur manquant -> None (AUD-342)."""
    try:
        if qty_contrats is None or contrat_usd is None or prix is None or prix == 0:
            return None
        notionnel = float(qty_contrats) * float(contrat_usd)
        return notionnel
    except (TypeError, ValueError):
        return None

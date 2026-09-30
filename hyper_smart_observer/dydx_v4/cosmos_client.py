"""
Client Cosmos LCD pour dYdX v4 — découverte de wallets.

READ-ONLY. Aucune clé privée. Aucune signature. Aucun ordre.
Utilise le endpoint public: https://dydx-rest.publicnode.com
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

COSMOS_LCD_URL = "https://dydx-rest.publicnode.com"
USDC_ASSET_ID = 0
USDC_DECIMALS = 6  # quantums / 10^6 = USDC

# perpetual_id → (ticker, atomic_resolution)
# Source: GET /dydxprotocol/perpetuals/perpetual (live, mai 2026)
PERPETUAL_ID_MAP: dict[int, tuple[str, int]] = {
    0: ("BTC-USD", -10), 1: ("ETH-USD", -9), 2: ("LINK-USD", -6),
    5: ("SOL-USD", -7), 6: ("ADA-USD", -5), 7: ("AVAX-USD", -7),
    9: ("LTC-USD", -7), 10: ("DOGE-USD", -4), 11: ("ATOM-USD", -6),
    12: ("DOT-USD", -6), 13: ("UNI-USD", -6), 22: ("APE-USD", -6),
    23: ("APT-USD", -6), 24: ("ARB-USD", -6), 27: ("OP-USD", -6),
    28: ("PEPE-USD", 1), 29: ("SEI-USD", -5), 31: ("SUI-USD", -5),
    32: ("XRP-USD", -5), 33: ("TIA-USD", -7), 36: ("AAVE-USD", -7),
    37: ("BNB-USD", -8), 41: ("ICP-USD", -7), 42: ("DYM-USD", -6),
    43: ("STRK-USD", -6), 46: ("PYTH-USD", -5), 47: ("BONK-USD", -1),
    51: ("INJ-USD", -7), 57: ("RUNE-USD", -6), 63: ("DYDX-USD", -6),
    65: ("WIF-USD", -6), 74: ("ZRO-USD", -6), 75: ("ZK-USD", -5),
    77: ("ONDO-USD", -6), 78: ("ENA-USD", -5), 85: ("TAO-USD", -8),
    93: ("BLAST-USD", -4), 94: ("XMR-USD", -8),
}

# Marchés liquides considérés pour le copy-trading
LIQUID_MARKETS = frozenset([
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "BNB-USD",
    "DOGE-USD", "XRP-USD", "TIA-USD", "ARB-USD", "OP-USD",
])


def quantums_to_size(quantums: int, atomic_resolution: int) -> float:
    """Convertit les quantums on-chain en taille réelle."""
    return quantums * (10 ** atomic_resolution)


def usdc_quantums_to_float(quantums: int) -> float:
    """Convertit les quantums USDC en USD réels."""
    return quantums / (10 ** USDC_DECIMALS)


@dataclass
class OnChainPosition:
    """Position perpétuelle lue depuis la chaîne (lecture seule)."""
    perpetual_id: int
    market_id: str
    size: float          # positif = LONG, négatif = SHORT
    side: str            # "LONG" ou "SHORT"
    notional_approx: float = 0.0  # estimé avec oracle price si disponible
    atomic_resolution: int = -6


@dataclass
class OnChainSubaccount:
    """Subaccount lu depuis le Cosmos LCD (lecture seule)."""
    address: str
    subaccount_number: int
    usdc_balance: float
    positions: list[OnChainPosition] = field(default_factory=list)
    has_active_positions: bool = False
    total_position_count: int = 0
    fetched_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class DydxCosmosLcdClient:
    """
    Client READ-ONLY pour le Cosmos LCD de dYdX v4.
    Découverte de wallets via scan de tous les subaccounts.
    Aucune clé privée, aucun ordre, aucune signature.
    """

    def __init__(
        self,
        lcd_url: str = COSMOS_LCD_URL,
        timeout_s: float = 15.0,
        rate_limit_s: float = 0.2,
    ) -> None:
        self.lcd_url = lcd_url.rstrip("/")
        self.timeout_s = timeout_s
        self.rate_limit_s = rate_limit_s
        self._last_call: float = 0.0

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """GET HTTP avec rate limiting."""
        try:
            import requests as req
        except ImportError:
            logger.error("requests non installé")
            return None

        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.rate_limit_s:
            time.sleep(self.rate_limit_s - elapsed)
        self._last_call = time.monotonic()

        url = f"{self.lcd_url}{path}"
        try:
            resp = req.get(url, params=params, timeout=self.timeout_s)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("LCD GET %s → %d", path, resp.status_code)
            return None
        except Exception as e:
            logger.error("LCD GET error %s: %s", path, e)
            return None

    def scan_subaccounts(
        self,
        max_pages: int = 50,
        page_size: int = 100,
        min_usdc: float = 5_000.0,
        only_with_positions: bool = True,
    ) -> list[OnChainSubaccount]:
        """
        Paginer tous les subaccounts on-chain, filtrer par balance et positions.

        Args:
            max_pages: pages max (100 subcomptes/page → max 5000 comptes)
            page_size: subaccounts par page
            min_usdc: balance minimum USDC (filtre les petits comptes)
            only_with_positions: ne garder que les comptes avec positions ouvertes

        Returns:
            Liste de subaccounts filtrés, triés par balance décroissante
        """
        results: list[OnChainSubaccount] = []
        next_key: Optional[str] = None

        for page in range(max_pages):
            params: dict = {"pagination.limit": page_size}
            if next_key:
                params["pagination.key"] = next_key

            data = self._get("/dydxprotocol/subaccounts/subaccount", params=params)
            if not data:
                break

            for raw in data.get("subaccount", []):
                parsed = self._parse_subaccount(raw)
                if parsed is None:
                    continue
                if parsed.usdc_balance < min_usdc:
                    continue
                if only_with_positions and not parsed.has_active_positions:
                    continue
                results.append(parsed)

            pagination = data.get("pagination", {})
            next_key = pagination.get("next_key")
            if not next_key:
                break

            logger.debug(
                "LCD scan page=%d found=%d total_so_far=%d",
                page + 1, len(data.get("subaccount", [])), len(results)
            )

        results.sort(key=lambda x: x.usdc_balance, reverse=True)
        logger.info("LCD scan done: %d wallets with min_usdc=%.0f positions=%s",
                    len(results), min_usdc, only_with_positions)
        return results

    def _parse_subaccount(self, raw: dict) -> Optional[OnChainSubaccount]:
        """Parser un subaccount brut depuis la chaîne."""
        try:
            acc_id = raw.get("id", {})
            address = acc_id.get("owner", "")
            if not address or not address.startswith("dydx"):
                return None
            sub_num = int(acc_id.get("number", 0))

            # Balance USDC
            usdc_balance = 0.0
            for ap in raw.get("asset_positions", []):
                if int(ap.get("asset_id", -1)) == USDC_ASSET_ID:
                    usdc_balance = usdc_quantums_to_float(int(ap.get("quantums", 0)))
                    break

            # Positions ouvertes
            positions: list[OnChainPosition] = []
            for pp in raw.get("perpetual_positions", []):
                perp_id = int(pp.get("perpetual_id", -1))
                quantums = int(pp.get("quantums", 0))
                if quantums == 0:
                    continue

                ticker, atomic_res = PERPETUAL_ID_MAP.get(perp_id, (None, -6))
                if ticker is None:
                    ticker = f"PERP_{perp_id}-USD"

                real_size = quantums_to_size(abs(quantums), atomic_res)
                side = "LONG" if quantums > 0 else "SHORT"

                positions.append(OnChainPosition(
                    perpetual_id=perp_id,
                    market_id=ticker,
                    size=real_size,
                    side=side,
                    atomic_resolution=atomic_res,
                ))

            return OnChainSubaccount(
                address=address,
                subaccount_number=sub_num,
                usdc_balance=usdc_balance,
                positions=positions,
                has_active_positions=len(positions) > 0,
                total_position_count=len(positions),
            )
        except Exception as e:
            logger.debug("Parse subaccount error: %s | raw=%s", e, str(raw)[:100])
            return None

    def get_subaccount(self, address: str, sub_num: int = 0) -> Optional[OnChainSubaccount]:
        """Récupérer un seul subaccount par adresse."""
        data = self._get(f"/dydxprotocol/subaccounts/subaccount/{address}/{sub_num}")
        if not data:
            return None
        raw = data.get("subaccount")
        if not raw:
            return None
        return self._parse_subaccount(raw)

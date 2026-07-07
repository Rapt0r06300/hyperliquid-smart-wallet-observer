"""
Client REST Indexer dYdX v4 — READ-ONLY.

Toutes les requêtes sont GET uniquement.
Aucune authentification, aucune clé privée.
Retry, backoff, rate limiter, cache, erreurs typées.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False
    logger.warning("aiohttp non disponible — REST client en mode dégradé (requests sync)")

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False


@dataclass
class RestError(Exception):
    """Erreur typée du client REST."""
    status_code: int
    message: str
    url: str = ""
    raw: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"RestError({self.status_code}): {self.message} [url={self.url}]"


@dataclass
class RateLimiter:
    """Rate limiter simple (tokens par seconde)."""
    rps: float = 5.0
    _last_call: float = field(default=0.0, init=False)

    def wait_sync(self) -> None:
        now = time.monotonic()
        min_interval = 1.0 / self.rps
        elapsed = now - self._last_call
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call = time.monotonic()

    async def wait_async(self) -> None:
        now = time.monotonic()
        min_interval = 1.0 / self.rps
        elapsed = now - self._last_call
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_call = time.monotonic()


class DydxIndexerRestClient:
    """
    Client REST pour l'Indexer dYdX v4.

    READ-ONLY: uniquement des GET, jamais de POST/PUT/DELETE.
    Pas d'authentification, pas de clé privée.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 10.0,
        max_retries: int = 3,
        backoff_base_s: float = 1.0,
        rate_limit_rps: float = 5.0,
        fallback_base_urls: Optional[list[str]] = None,
        bypass_proxy: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self._rate_limiter = RateLimiter(rps=rate_limit_rps)
        self._session: Optional[Any] = None  # aiohttp.ClientSession
        # Chaîne de fallback: essayer base_url en premier, puis les alternatives
        self._all_base_urls: list[str] = [base_url.rstrip("/")]
        for fb in (fallback_base_urls or []):
            fb = fb.rstrip("/")
            if fb not in self._all_base_urls:
                self._all_base_urls.append(fb)
        # Bypass proxy Windows (403 Forbidden tunnel): passer proxies=None explicitement
        self._proxies: Optional[dict] = {"http": None, "https": None} if bypass_proxy else None

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    # ----------------------------------------------------------------------- #
    # Health
    # ----------------------------------------------------------------------- #

    def get_health(self) -> dict:
        """GET /v4/height — health check."""
        return self._get_sync("/v4/height")

    # ----------------------------------------------------------------------- #
    # Markets
    # ----------------------------------------------------------------------- #

    def get_markets(self) -> dict:
        """GET /v4/perpetualMarkets — liste tous les marchés perpétuels."""
        return self._get_sync("/v4/perpetualMarkets")

    def get_market(self, market_id: str) -> dict:
        """GET /v4/perpetualMarkets/{market_id}."""
        return self._get_sync(f"/v4/perpetualMarkets/{market_id}")

    def get_orderbook(self, market_id: str) -> dict:
        """GET /v4/orderbooks/perpetualMarket/{market_id}."""
        return self._get_sync(f"/v4/orderbooks/perpetualMarket/{market_id}")

    def get_candles(
        self,
        market_id: str,
        resolution: str = "1MIN",
        limit: int = 100,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
    ) -> dict:
        """GET /v4/candles/perpetualMarkets/{market_id}."""
        params: dict[str, Any] = {"resolution": resolution, "limit": limit}
        if from_iso:
            params["fromISO"] = from_iso
        if to_iso:
            params["toISO"] = to_iso
        return self._get_sync(f"/v4/candles/perpetualMarkets/{market_id}", params=params)

    def get_trades(self, market_id: str, limit: int = 100) -> dict:
        """GET /v4/trades/perpetualMarket/{market_id}."""
        return self._get_sync(
            f"/v4/trades/perpetualMarket/{market_id}", params={"limit": limit}
        )

    # ----------------------------------------------------------------------- #
    # Accounts / Subaccounts (READ-ONLY public Indexer)
    # ----------------------------------------------------------------------- #

    def get_subaccount(self, address: str, subaccount_number: int = 0) -> dict:
        """GET /v4/addresses/{address}/subaccountNumber/{n}."""
        return self._get_sync(
            f"/v4/addresses/{address}/subaccountNumber/{subaccount_number}"
        )

    def get_subaccounts(self, address: str) -> dict:
        """GET /v4/addresses/{address} — tous les subaccounts."""
        return self._get_sync(f"/v4/addresses/{address}")

    def get_positions(
        self,
        address: str,
        subaccount_number: int = 0,
        status: str = "OPEN",
        limit: int = 100,
    ) -> dict:
        """GET /v4/perpetualPositions."""
        return self._get_sync(
            "/v4/perpetualPositions",
            params={
                "address": address,
                "subaccountNumber": subaccount_number,
                "status": status,
                "limit": limit,
            },
        )

    def get_orders(
        self,
        address: str,
        subaccount_number: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> dict:
        """GET /v4/orders."""
        params: dict[str, Any] = {
            "address": address,
            "subaccountNumber": subaccount_number,
            "limit": limit,
        }
        if status:
            params["status"] = status
        return self._get_sync("/v4/orders", params=params)

    def get_fills(
        self,
        address: str,
        subaccount_number: int = 0,
        market_id: Optional[str] = None,
        limit: int = 100,
        created_before_or_at_ms: Optional[int] = None,
    ) -> dict:
        """GET /v4/fills — avec pagination cursor."""
        params: dict[str, Any] = {
            "address": address,
            "subaccountNumber": subaccount_number,
            "limit": limit,
        }
        if market_id:
            params["market"] = market_id
            params["marketType"] = "PERPETUAL"
        if created_before_or_at_ms:
            import datetime
            dt = datetime.datetime.utcfromtimestamp(created_before_or_at_ms / 1000)
            params["createdBeforeOrAtHeight"] = None  # utiliser ISO si disponible
            params["createdBeforeOrAt"] = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return self._get_sync("/v4/fills", params=params)

    def get_historical_pnl(
        self,
        address: str,
        subaccount_number: int = 0,
        limit: int = 100,
    ) -> dict:
        """GET /v4/historicalPnl — PnL historique du subaccount."""
        return self._get_sync(
            "/v4/historicalPnl",
            params={
                "address": address,
                "subaccountNumber": subaccount_number,
                "limit": limit,
            },
        )

    def paginate_fills(
        self,
        address: str,
        subaccount_number: int = 0,
        max_pages: int = 10,
        page_size: int = 100,
    ) -> list[dict]:
        """Paginer tous les fills d'un subaccount (backfill)."""
        all_fills: list[dict] = []
        cursor_ms: Optional[int] = None

        for page in range(max_pages):
            try:
                resp = self.get_fills(
                    address=address,
                    subaccount_number=subaccount_number,
                    limit=page_size,
                    created_before_or_at_ms=cursor_ms,
                )
                fills = resp.get("fills", [])
                if not fills:
                    break
                all_fills.extend(fills)

                # Cursor = timestamp du dernier fill (le plus ancien)
                last = fills[-1]
                created = last.get("createdAt", "")
                if created:
                    try:
                        import datetime
                        dt = datetime.datetime.fromisoformat(
                            created.replace("Z", "+00:00")
                        )
                        cursor_ms = int(dt.timestamp() * 1000) - 1
                    except Exception:
                        break
                else:
                    break

                logger.debug(
                    "Fills paginated: page=%d total=%d address=%s",
                    page + 1,
                    len(all_fills),
                    address,
                )

                if len(fills) < page_size:
                    break

            except RestError as e:
                logger.error("Pagination fills error page=%d: %s", page, e)
                break

        return all_fills

    # ----------------------------------------------------------------------- #
    # HTTP GET interne — sync avec retry/backoff
    # ----------------------------------------------------------------------- #

    def _url_for(self, base: str, path: str) -> str:
        return urljoin(base + "/", path.lstrip("/"))

    def _get_sync(self, path: str, params: Optional[dict] = None) -> dict:
        """GET HTTP synchrone avec proxy bypass, retry et fallback sur endpoints alternatifs.

        Essaie chaque base_url dans self._all_base_urls jusqu'à succès.
        Proxy Windows bypassé via proxies={http: None, https: None}.
        """
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError(
                "requests non disponible — installer avec: pip install requests"
            )

        last_error: Optional[Exception] = None

        for base_url in self._all_base_urls:
            url = self._url_for(base_url, path)

            for attempt in range(self.max_retries + 1):
                try:
                    self._rate_limiter.wait_sync()
                    resp = requests.get(
                        url,
                        params=params,
                        timeout=self.timeout_s,
                        proxies=self._proxies,  # None→bypass proxy sys. Windows
                    )

                    if resp.status_code == 200:
                        # Mettre à jour base_url actif si on a utilisé un fallback
                        if base_url != self.base_url:
                            logger.info("Fallback endpoint actif: %s", base_url)
                            self.base_url = base_url
                        return resp.json()
                    elif resp.status_code == 429:
                        wait = self.backoff_base_s * (2 ** attempt)
                        logger.warning("Rate limited (429) %s, wait=%.1fs", base_url, wait)
                        time.sleep(wait)
                        continue
                    elif resp.status_code in (500, 502, 503, 504):
                        wait = self.backoff_base_s * (2 ** attempt)
                        logger.warning("Server error %d %s, wait=%.1fs", resp.status_code, base_url, wait)
                        time.sleep(wait)
                        continue
                    else:
                        try:
                            body = resp.json()
                        except Exception:
                            body = {}
                        # 403/401 probablement proxy → essayer le prochain endpoint
                        if resp.status_code in (403, 401, 407):
                            logger.warning(
                                "Proxy/auth error %d sur %s, essai fallback…",
                                resp.status_code, base_url,
                            )
                            last_error = RestError(
                                status_code=resp.status_code,
                                message=f"Proxy/auth error sur {base_url}",
                                url=url,
                                raw=body,
                            )
                            break  # Sortir de la boucle attempt → essayer le prochain base_url
                        raise RestError(
                            status_code=resp.status_code,
                            message=body.get("errors", [{"msg": resp.text}])[0].get("msg", resp.text)
                            if isinstance(body.get("errors"), list) and body.get("errors")
                            else str(body),
                            url=url,
                            raw=body,
                        )

                except RestError:
                    raise
                except Exception as e:
                    last_error = e
                    wait = self.backoff_base_s * (2 ** attempt)
                    logger.warning("Request error %s attempt=%d wait=%.1fs: %s", base_url, attempt, wait, e)
                    if attempt < self.max_retries:
                        time.sleep(wait)
                    else:
                        break  # Prochain endpoint

        raise RestError(
            status_code=0,
            message=f"Tous les endpoints ont échoué (max_retries={self.max_retries}): {last_error}",
            url=path,
        )

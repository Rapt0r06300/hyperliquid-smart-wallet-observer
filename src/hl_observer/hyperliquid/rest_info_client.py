from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from hl_observer.sources.collection_recorder import CollectionRecorder

from hl_observer.collection.vault_fills_backfill import (
    plan_de_requetes,
    split_inclusive_window,
)
from hl_observer.hyperliquid.rate_limits import AsyncRateLimiter
from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT,
    HYPERSMART_USER_FILLS_RECENT_LIMIT,
    HYPERSMART_USER_TWAP_SLICE_FILLS_RECENT_LIMIT,
)
from hl_observer.hyperliquid.schemas import (
    REJECTED_ORDER_STATUSES,
    OrderStatus,
    OrderStatusKind,
)
from hl_observer.ops.echec_silencieux import noter as _noter_echec
from hl_observer.security.mainnet_guard import assert_info_endpoint_only

MAX_USER_FILLS_PAGE_SIZE = HYPERSMART_USER_FILLS_RECENT_LIMIT
READ_ONLY_INFO_TYPES = {
    "meta",
    "activeAssetCtx",
    "allMids",
    "l2Book",
    "clearinghouseState",
    "openOrders",
    "frontendOpenOrders",
    "userFills",
    "userFillsByTime",
    "userTwapSliceFills",
    "orderStatus",
    "candleSnapshot",
    "portfolio",
    "historicalOrders",
    "userFunding",
    "userRateLimit",
    # --- 2026-07-13 : deux endpoints PUBLICS en LECTURE SEULE qui manquaient a l'allowlist ---
    # `fundingHistory` : le funding REALISE par coin, avec startTime -> des MOIS d'historique.
    #   X-04 a ete mesure sur 18,9 h de funding enregistre en live. C'etait inutile : l'historique
    #   etait public. (Meme maladie que `candleSnapshot(startTime)` : la capacite etait la.)
    # `predictedFundings` : le funding de **Binance / Bybit / HL** sur le **MEME coin**.
    #   -> src/hl_observer/funding/funding_cross_venue.py
    # Les deux sont /info, sans wallet, sans signature. Ils ne peuvent RIEN executer.
    "fundingHistory",
    "predictedFundings",
    # 🔴 2026-07-14 — LA VRAIE LISTE DES MARCHES SPOT. **Je la SUPPOSAIS ({HYPE, PURR}).**
    # Le carry EXIGE une jambe spot : sans elle, on est short le perp A NU (pari directionnel).
    # `spotMeta` est /info, public, sans wallet, sans signature. **On demande au lieu de deviner.**
    "spotMeta",
    "spotMetaAndAssetCtxs",
    # --- 2026-07-13 : #517 -- les marches HIP-3 (perps deployes par des builders) ---
    # `perpDexs` liste les dex ; `meta` accepte un champ `dex`. Les coins s'y nomment `{dex}:{coin}`
    # (doc : for-developers/api/asset-ids). C'est la SEULE reouverture legitime du market making :
    # le « growth mode » divise les frais par 10. -> market/hip3_markets.py
    # /info, sans wallet, sans signature. Ne peut RIEN executer.
    "perpDexs",
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🎯 2026-07-14 — `vaultDetails` : **LE BENCHMARK QUI JUGE TOUT.**
    #
    # J'ai ecrit dans `tools/tous_les_leviers.py` : « HLP rapporte 10 a 30 % APR ».
    #     ***C'est un chiffre que j'ai SUPPOSE.*** C'est exactement le peche que ce projet
    #     punit depuis deux jours : DEVINER au lieu de DEMANDER.
    #     (3e fois : `candleSnapshot(startTime)`, `fundingHistory`, la liste des spot.)
    #
    # Or le benchmark decide de TOUT : si notre carry rend 5 % et que HLP rend 15 %, alors
    # **toute notre complexite est dominee par un virement.** Un benchmark suppose peut donc
    # faire passer un perdant pour un gagnant -- ou l'inverse.
    #
    # `vaultDetails` est /info, public, sans wallet, sans signature. Il ne peut RIEN executer.
    # -> src/hl_observer/market/hlp_vault.py (qui etait PUR et sans donnee : encore un chainon)
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    "vaultDetails",
}


class HyperliquidInfoError(RuntimeError):
    """Raised when a read-only Hyperliquid info call fails."""

    def __init__(
        self,
        message: str,
        *,
        coverage_receipt: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.coverage_receipt = copy.deepcopy(coverage_receipt)


def _ensure_read_only_payload(payload: dict[str, Any]) -> None:
    request_type = payload.get("type")
    if request_type not in READ_ONLY_INFO_TYPES:
        raise HyperliquidInfoError(f"Unsupported read-only info type: {request_type!r}")


def stable_json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_all_mids_payload() -> dict[str, Any]:
    return {"type": "allMids"}


def build_meta_payload() -> dict[str, Any]:
    return {"type": "meta"}


def build_active_asset_ctx_payload(coin: str) -> dict[str, Any]:
    return {"type": "activeAssetCtx", "coin": coin.upper()}


def build_l2_book_payload(coin: str) -> dict[str, Any]:
    return {"type": "l2Book", "coin": coin.upper()}


def build_open_orders_payload(user: str) -> dict[str, Any]:
    return {"type": "openOrders", "user": user}


def build_clearinghouse_state_payload(user: str) -> dict[str, Any]:
    return {"type": "clearinghouseState", "user": user}


def build_frontend_open_orders_payload(user: str) -> dict[str, Any]:
    return {"type": "frontendOpenOrders", "user": user}


def build_user_fills_payload(user: str, aggregate_by_time: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "userFills", "user": user}
    if aggregate_by_time:
        payload["aggregateByTime"] = True
    return payload


def build_user_fills_by_time_payload(
    user: str,
    start_time: int,
    end_time: int,
    aggregate_by_time: bool = False,
) -> dict[str, Any]:
    if start_time > end_time:
        raise ValueError("start_time must not exceed end_time")
    payload: dict[str, Any] = {
        "type": "userFillsByTime",
        "user": user,
        "startTime": int(start_time),
        "endTime": int(end_time),
    }
    if aggregate_by_time:
        payload["aggregateByTime"] = True
    return payload


def build_user_twap_slice_fills_payload(user: str) -> dict[str, Any]:
    return {"type": "userTwapSliceFills", "user": user}


def build_order_status_payload(user: str, oid_or_cloid: int | str) -> dict[str, Any]:
    return {"type": "orderStatus", "user": user, "oid": oid_or_cloid}


def build_portfolio_payload(user: str) -> dict[str, Any]:
    return {"type": "portfolio", "user": user}


def build_historical_orders_payload(user: str) -> dict[str, Any]:
    return {"type": "historicalOrders", "user": user}


def build_user_funding_payload(
    user: str, start_time: int | None = None, end_time: int | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "userFunding", "user": user}
    if start_time is not None:
        payload["startTime"] = int(start_time)
    if end_time is not None:
        payload["endTime"] = int(end_time)
    return payload


def build_user_rate_limit_payload(user: str) -> dict[str, Any]:
    return {"type": "userRateLimit", "user": user}


def build_funding_history_payload(
    coin: str,
    start_time: int,
    end_time: int | None = None,
) -> dict[str, Any]:
    """Le funding REALISE d'un coin, avec startTime. Public, sans wallet, sans signature.

    X-04 a juge le funding sur **18,9 h** enregistrees en live. Cet endpoint donne des **mois**.
    """
    if end_time is not None and int(start_time) >= int(end_time):
        raise ValueError("start_time must be strictly lower than end_time")
    payload: dict[str, Any] = {
        "type": "fundingHistory",
        "coin": coin.upper(),
        "startTime": int(start_time),
    }
    if end_time is not None:
        payload["endTime"] = int(end_time)
    return payload


def build_predicted_fundings_payload() -> dict[str, Any]:
    """Le funding de **Binance / Bybit / Hyperliquid** sur le **MEME coin**.

    C'est la seule forme de couverture qui obeit a la loi mesuree le 2026-07-13 :
    ***une couverture ne vaut que si c'est le MEME actif***. Voir funding/funding_cross_venue.py
    """
    return {"type": "predictedFundings"}


def build_candle_snapshot_payload(
    coin: str,
    interval: str,
    start_time: int,
    end_time: int,
) -> dict[str, Any]:
    if start_time >= end_time:
        raise ValueError("start_time must be strictly lower than end_time")
    return {
        "type": "candleSnapshot",
        "req": {
            "coin": coin.upper(),
            "interval": interval,
            "startTime": int(start_time),
            "endTime": int(end_time),
        },
    }


def map_order_status(payload: dict[str, Any]) -> OrderStatus:
    raw_status = payload.get("status")
    status = OrderStatusKind.UNKNOWN
    if isinstance(raw_status, str):
        try:
            status = OrderStatusKind(raw_status)
        except ValueError:
            status = OrderStatusKind.UNKNOWN
    return OrderStatus(
        status=status,
        is_rejected=status in REJECTED_ORDER_STATUSES,
        raw=payload,
    )


class HyperliquidInfoClient:
    """Small, read-only client for Hyperliquid's /info API."""

    def __init__(
        self,
        base_url: str = "https://api.hyperliquid.xyz/info",
        *,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.25,
        client: httpx.AsyncClient | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
        recorder: CollectionRecorder | None = None,
    ) -> None:
        if not base_url.endswith("/info"):
            raise HyperliquidInfoError("HyperliquidInfoClient must target the /info endpoint only")
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self._client = client
        self._owns_client = client is None
        self._rate_limiter = rate_limiter or AsyncRateLimiter()
        # Optional, opt-in provenance recorder (V12 A+E). Best-effort: never breaks fetches.
        self._recorder = recorder

    async def __aenter__(self) -> HyperliquidInfoClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_client = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    async def _post_info(self, request_type: str, payload: dict[str, Any] | None = None) -> Any:
        payload = {"type": request_type, **(payload or {})}
        _ensure_read_only_payload(payload)
        # 🔴 #254 -- LE GARDE-FOU QUI EXISTAIT ET QUE PERSONNE N'APPELAIT (2026-07-13).
        #
        # `assert_info_endpoint_only` vit dans security/mainnet_guard.py depuis des semaines.
        # Elle a ete ecrite POUR CA -- garantir qu'on ne frappe QUE `/info`. AST : **0 appelant.**
        # 14e deguisement de la maladie du projet : *une capacite presente, un chainon manquant,
        # personne qui se plaint.*
        #
        # On la branche ICI, au TRANSPORT -- pas chez l'appelant. La difference est tout :
        # un garde chez l'appelant protege CET appelant ; un garde au transport protege
        # **tous les appelants, y compris ceux qui n'existent pas encore.** Si un jour du code
        # (humain ou agent) construisait une URL d'EXECUTION, la requete ne partirait PAS.
        #
        # 🚩 (Et ce commentaire a ete REECRIT : ma 1re version citait le nom litteral de
        # l'endpoint d'execution -- ce qui a fait ROUGIR `test_rest_info_client_v6`, un garde
        # STATIQUE qui interdit cette chaine dans cette classe. Le garde avait raison. On
        # reformule le commentaire ; on n'affaiblit JAMAIS le garde.)
        #
        # Les 8 controles de `safety-audit` sont STATIQUES (ils lisent le source). Celui-ci est
        # le premier controle **RUNTIME** : il agit a l'instant ou l'octet allait partir.
        assert_info_endpoint_only(self.base_url)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_client = True

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self._rate_limiter.wait()
            try:
                response = await self._client.post(self.base_url, json=payload)
                response.raise_for_status()
                data = response.json()
                self._record_fetch(request_type, data, ok=True, error=None)
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(self.backoff_base_seconds * (2**attempt))
        self._record_fetch(request_type, None, ok=False, error=str(last_error))
        raise HyperliquidInfoError(f"Hyperliquid /info call failed: {last_error}") from last_error

    def _record_fetch(self, request_type: str, response: object, *, ok: bool, error: str | None) -> None:
        """Forward one fetch to the optional provenance recorder. Never raises."""
        recorder = getattr(self, "_recorder", None)
        if recorder is None:
            return
        try:
            recorder.record_rest(request_type=request_type, response=response, ok=ok, error=error)
        except Exception:
            _noter_echec("hl_observer/hyperliquid/rest_info_client.py:324")

    async def all_mids(self) -> dict[str, str]:
        data = await self._post_info("allMids")
        if not isinstance(data, dict):
            raise HyperliquidInfoError("allMids returned a non-object payload")
        return data

    async def meta(self) -> dict[str, Any]:
        data = await self._post_info("meta")
        if not isinstance(data, dict):
            raise HyperliquidInfoError("meta returned a non-object payload")
        return data

    async def active_asset_ctx(self, coin: str) -> dict[str, Any]:
        data = await self._post_info("activeAssetCtx", {"coin": coin.upper()})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("activeAssetCtx returned a non-object payload")
        return data

    async def l2_book(self, coin: str) -> dict[str, Any]:
        data = await self._post_info("l2Book", {"coin": coin.upper()})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("l2Book returned a non-object payload")
        return data

    async def open_orders(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info("openOrders", {"user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("openOrders returned a non-list payload")
        return data

    async def clearinghouse_state(self, user: str) -> dict[str, Any]:
        data = await self._post_info("clearinghouseState", {"user": user})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("clearinghouseState returned a non-object payload")
        return data

    async def frontend_open_orders(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info("frontendOpenOrders", {"user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("frontendOpenOrders returned a non-list payload")
        return data

    async def user_fills(
        self,
        user: str,
        aggregate_by_time: bool = False,
    ) -> list[dict[str, Any]]:
        payload = {"user": user}
        if aggregate_by_time:
            payload["aggregateByTime"] = True
        data = await self._post_info("userFills", payload)
        if not isinstance(data, list):
            raise HyperliquidInfoError("userFills returned a non-list payload")
        if len(data) > MAX_USER_FILLS_PAGE_SIZE:
            raise HyperliquidInfoError("userFills exceeded the documented 2000 item limit")
        return data

    async def user_fills_by_time(
        self,
        user: str,
        start_time: int,
        end_time: int,
        aggregate_by_time: bool = False,
    ) -> list[dict[str, Any]]:
        payload = build_user_fills_by_time_payload(
            user,
            start_time,
            end_time,
            aggregate_by_time=aggregate_by_time,
        )
        request_payload = {key: value for key, value in payload.items() if key != "type"}
        data = await self._post_info("userFillsByTime", request_payload)
        if not isinstance(data, list):
            raise HyperliquidInfoError("userFillsByTime returned a non-list payload")
        if len(data) > MAX_USER_FILLS_PAGE_SIZE:
            raise HyperliquidInfoError("userFillsByTime exceeded the documented 2000 item limit")
        return data

    async def user_twap_slice_fills(
        self,
        user: str,
    ) -> list[dict[str, Any]]:
        data = await self._post_info("userTwapSliceFills", {"user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("userTwapSliceFills returned a non-list payload")
        if len(data) > HYPERSMART_USER_TWAP_SLICE_FILLS_RECENT_LIMIT:
            raise HyperliquidInfoError("userTwapSliceFills exceeded the documented 2000 item limit")
        return data

    async def iter_user_fills_by_time(
        self,
        user: str,
        start_time: int,
        end_time: int,
        page_window_ms: int | None = None,
        max_pages: int | None = None,
        aggregate_by_time: bool = False,
        min_window_ms: int = 0,
        response_cap: int = MAX_USER_FILLS_PAGE_SIZE,
        audit: dict[str, Any] | None = None,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        async for page, _, _ in self._iter_user_fills_by_time_windows(
            user,
            start_time,
            end_time,
            page_window_ms=page_window_ms,
            max_pages=max_pages,
            aggregate_by_time=aggregate_by_time,
            min_window_ms=min_window_ms,
            response_cap=response_cap,
            audit=audit,
        ):
            yield page

    async def _iter_user_fills_by_time_windows(
        self,
        user: str,
        start_time: int,
        end_time: int,
        page_window_ms: int | None = None,
        max_pages: int | None = None,
        aggregate_by_time: bool = False,
        min_window_ms: int = 0,
        response_cap: int = MAX_USER_FILLS_PAGE_SIZE,
        audit: dict[str, Any] | None = None,
    ) -> AsyncIterator[tuple[list[dict[str, Any]], int, int]]:
        if end_time < start_time:
            raise HyperliquidInfoError("userFillsByTime end_time precedes start_time")
        if page_window_ms is not None and page_window_ms < 0:
            raise HyperliquidInfoError("userFillsByTime pagination window did not advance")
        if min_window_ms < 0:
            raise HyperliquidInfoError("userFillsByTime minimum window cannot be negative")
        if not 0 < int(response_cap) <= MAX_USER_FILLS_PAGE_SIZE:
            raise HyperliquidInfoError("userFillsByTime response cap exceeds the official API limit")

        window_ms = (
            int(page_window_ms)
            if page_window_ms
            else max(1, int(end_time) - int(start_time))
        )
        pending: deque[tuple[int, int]] = deque(
            plan_de_requetes(start_time, end_time, fenetre_ms=window_ms)
        )
        receipt = audit if audit is not None else {}
        receipt.clear()
        receipt.update(
            {
                "status": "IN_PROGRESS",
                "requested_start_ms": int(start_time),
                "requested_end_ms": int(end_time),
                "minimum_window_ms": int(min_window_ms),
                "api_response_cap": int(response_cap),
                "api_history_limit": HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT,
                "request_count": 0,
                "received_count": 0,
                "accepted_count": 0,
                "subrequests": [],
                "next_windows": [],
                "last_observed_boundary_ms": None,
                "usable_horizon_start_ms": None,
                "usable_horizon_end_ms": None,
                "historical_capture": "REST_BOUNDED",
                "prospective_capture_separate": True,
                "historical_censored": False,
            }
        )

        pages_seen = 0
        seen_page_hashes: set[str] = set()
        while pending:
            if max_pages is not None and pages_seen >= max_pages:
                receipt["status"] = "PARTIAL"
                receipt["reason"] = "MAX_PAGES_REACHED"
                receipt["next_windows"] = [
                    {"start_ms": left, "end_ms": right}
                    for left, right in pending
                ]
                raise HyperliquidInfoError(
                    "userFillsByTime max_pages exhausted before the requested range; "
                    f"{len(pending)} window(s) remain, starting at "
                    f"[{pending[0][0]}, {pending[0][1]}]; coverage is incomplete",
                    coverage_receipt=receipt,
                )
            window_start, window_end = pending.popleft()
            attempt: dict[str, Any] = {
                "start_ms": window_start,
                "end_ms": window_end,
                "cursor_ms": window_start,
                "api_response_cap": int(response_cap),
                "response_rows": None,
                "last_observed_boundary_ms": None,
                "outcome": "REQUESTED",
            }
            receipt["subrequests"].append(attempt)
            receipt["request_count"] += 1
            try:
                page = await self.user_fills_by_time(
                    user,
                    window_start,
                    window_end,
                    aggregate_by_time=aggregate_by_time,
                )
            except Exception as exc:
                attempt["outcome"] = "FAILED"
                attempt["error_type"] = type(exc).__name__
                attempt["error"] = str(exc)[:300]
                receipt["status"] = "PARTIAL"
                receipt["reason"] = "REQUEST_FAILED"
                receipt["next_windows"] = [
                    {"start_ms": window_start, "end_ms": window_end},
                    *(
                        {"start_ms": left, "end_ms": right}
                        for left, right in pending
                    ),
                ]
                raise HyperliquidInfoError(
                    "userFillsByTime request failed for inclusive window "
                    f"[{window_start}, {window_end}]: {exc}",
                    coverage_receipt=receipt,
                ) from exc
            pages_seen += 1
            attempt["response_rows"] = len(page)
            receipt["received_count"] += len(page)
            if not page:
                attempt["outcome"] = "EMPTY"
                continue

            try:
                page_times = [int(fill["time"]) for fill in page]
            except (KeyError, TypeError, ValueError) as exc:
                attempt["outcome"] = "INVALID_TIMESTAMP"
                receipt["status"] = "PARTIAL"
                receipt["reason"] = "INVALID_TIMESTAMP"
                receipt["next_windows"] = [
                    {"start_ms": window_start, "end_ms": window_end},
                    *(
                        {"start_ms": left, "end_ms": right}
                        for left, right in pending
                    ),
                ]
                raise HyperliquidInfoError(
                    "userFillsByTime returned a fill without a valid timestamp",
                    coverage_receipt=receipt,
                ) from exc
            attempt["last_observed_boundary_ms"] = max(page_times)
            last_boundary = receipt.get("last_observed_boundary_ms")
            receipt["last_observed_boundary_ms"] = (
                max(int(last_boundary), max(page_times))
                if last_boundary is not None
                else max(page_times)
            )
            if any(not window_start <= timestamp <= window_end for timestamp in page_times):
                attempt["outcome"] = "OUT_OF_RANGE"
                receipt["status"] = "PARTIAL"
                receipt["reason"] = "OUT_OF_RANGE_FILL"
                receipt["next_windows"] = [
                    {"start_ms": window_start, "end_ms": window_end},
                    *(
                        {"start_ms": left, "end_ms": right}
                        for left, right in pending
                    ),
                ]
                raise HyperliquidInfoError(
                    "userFillsByTime returned a fill outside the requested inclusive window",
                    coverage_receipt=receipt,
                )

            if len(page) >= int(response_cap):
                split = split_inclusive_window(window_start, window_end)
                if split is None or window_end - window_start <= int(min_window_ms):
                    attempt["outcome"] = "CAP_BLOCKED"
                    receipt["status"] = "PARTIAL"
                    receipt["reason"] = (
                        "CAP_AT_MINIMUM_WINDOW"
                        if int(min_window_ms)
                        else "CAP_AT_MINIMUM_MILLISECOND"
                    )
                    receipt["next_windows"] = [
                        {"start_ms": window_start, "end_ms": window_end},
                        *(
                            {"start_ms": left, "end_ms": right}
                            for left, right in pending
                        ),
                    ]
                    minimum_label = (
                        f"configured minimum {int(min_window_ms)} ms window"
                        if int(min_window_ms)
                        else "minimum 1 ms window"
                    )
                    raise HyperliquidInfoError(
                        f"userFillsByTime reached the documented cap at the {minimum_label} "
                        f"[{window_start}, {window_end}]; coverage is incomplete",
                        coverage_receipt=receipt,
                    )
                attempt["outcome"] = "CAP_SPLIT"
                left, right = split
                pending.appendleft(right)
                pending.appendleft(left)
                continue

            page_hash = stable_json_hash(page)
            if page_hash in seen_page_hashes:
                attempt["outcome"] = "DUPLICATE_PAGE"
                receipt["status"] = "PARTIAL"
                receipt["reason"] = "DUPLICATE_PAGE"
                receipt["next_windows"] = [
                    {"start_ms": left, "end_ms": right}
                    for left, right in pending
                ]
                raise HyperliquidInfoError(
                    "Duplicate userFillsByTime page detected",
                    coverage_receipt=receipt,
                )
            seen_page_hashes.add(page_hash)
            attempt["outcome"] = "ACCEPTED"
            receipt["accepted_count"] += len(page)
            horizon_start = receipt["usable_horizon_start_ms"]
            horizon_end = receipt["usable_horizon_end_ms"]
            receipt["usable_horizon_start_ms"] = (
                min(int(horizon_start), min(page_times))
                if horizon_start is not None
                else min(page_times)
            )
            receipt["usable_horizon_end_ms"] = (
                max(int(horizon_end), max(page_times))
                if horizon_end is not None
                else max(page_times)
            )
            yield page, window_start, window_end

        receipt["historical_censored"] = (
            int(receipt["accepted_count"]) >= HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT
        )
        receipt["status"] = "PARTIAL" if receipt["historical_censored"] else "COMPLETE"
        receipt["reason"] = (
            "PUBLIC_RETENTION_LIMIT_REACHED" if receipt["historical_censored"] else None
        )
        receipt["next_windows"] = []
        if receipt["historical_censored"]:
            raise HyperliquidInfoError(
                "userFillsByTime reached the documented per-wallet history limit; "
                "older history may be censored",
                coverage_receipt=receipt,
            )

    async def order_status(self, user: str, oid_or_cloid: int | str) -> OrderStatus:
        data = await self._post_info("orderStatus", {"user": user, "oid": oid_or_cloid})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("orderStatus returned a non-object payload")
        status_payload = data.get("order") if isinstance(data.get("order"), dict) else data
        return map_order_status(status_payload)

    async def portfolio(self, user: str) -> Any:
        return await self._post_info("portfolio", {"user": user})

    async def historical_orders(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info("historicalOrders", {"user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("historicalOrders returned a non-list payload")
        return data

    async def user_funding(
        self,
        user: str,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict[str, Any]]:
        request = build_user_funding_payload(user, start_time=start_time, end_time=end_time)
        payload = {key: value for key, value in request.items() if key != "type"}
        data = await self._post_info("userFunding", payload)
        if not isinstance(data, list):
            raise HyperliquidInfoError("userFunding returned a non-list payload")
        return data

    async def user_rate_limit(self, user: str) -> dict[str, Any]:
        data = await self._post_info("userRateLimit", {"user": user})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("userRateLimit returned a non-object payload")
        return data

    async def funding_history(
        self,
        coin: str,
        start_time: int,
        end_time: int | None = None,
    ) -> list[dict[str, Any]]:
        """Le funding REALISE d'un coin. Public, avec startTime -> des MOIS d'historique.

        (X-04 avait juge le funding sur 18,9 h enregistrees en live. C'etait inutile.)
        """
        payload = build_funding_history_payload(coin, start_time, end_time)
        data = await self._post_info("fundingHistory", {k: v for k, v in payload.items() if k != "type"})
        if not isinstance(data, list):
            raise HyperliquidInfoError("fundingHistory returned a non-list payload")
        return data

    async def predicted_fundings(self) -> list[Any]:
        """Le funding de Binance / Bybit / HL sur le MEME coin. -> funding/funding_cross_venue.py"""
        data = await self._post_info("predictedFundings")
        if not isinstance(data, list):
            raise HyperliquidInfoError("predictedFundings returned a non-list payload")
        return data

    async def spot_meta(self) -> dict[str, Any]:
        """Les marches SPOT de HL : `tokens` (jetons) et `universe` (les PAIRES).

        🔑 **La distinction qui compte** : `l2Book` ne prend pas un nom de jeton, il prend le
        nom de la **PAIRE** (`PURR/USDC`, ou `@107`). Le mapping jeton -> paire se **CONSTRUIT**
        depuis `universe[].tokens` -- *on ne le devine pas* (c'est deja ce qui m'a fait supposer
        que seuls HYPE et PURR avaient du spot : il y en a **8**).

        /info, public, lecture seule. **Aucun ordre. Aucune signature.**
        """
        data = await self._post_info("spotMeta")
        if not isinstance(data, dict):
            raise HyperliquidInfoError("spotMeta returned a non-object payload")
        return data

    async def vault_details(self, vault_address: str) -> dict[str, Any]:
        """🎯 **LE BENCHMARK.** Le vault HLP -- *le market maker officiel de Hyperliquid.*

        Son rendement est **le PnL du market making sur HL, en argent reel, mesure par le
        protocole lui-meme.** C'est donc a la fois :

          * un **test direct de T1b** (fait par quelqu'un d'autre, avec du vrai argent) ;
          * et surtout **LE BENCHMARK QUI JUGE TOUT** : *si notre carry ne bat pas un depot
            passif dans HLP, toute notre complexite est dominee par un virement.*

        🚩 Un HLP gagnant ne REFUTE PAS T1b : HLP **encaisse une part des frais du protocole**
        et **EST le liquidateur**. *Le MM marche -- pour celui qui est PAYE pour le faire.*

        /info, public, lecture seule. **Aucun depot. Aucun ordre. Aucune signature.**
        """
        data = await self._post_info("vaultDetails", {"vaultAddress": str(vault_address)})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("vaultDetails returned a non-object payload")
        return data

    async def candle_snapshot(
        self,
        coin: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        payload = build_candle_snapshot_payload(
            coin,
            interval,
            start_time,
            end_time,
        )
        data = await self._post_info("candleSnapshot", {"req": payload["req"]})
        if not isinstance(data, list):
            raise HyperliquidInfoError("candleSnapshot returned a non-list payload")
        return data

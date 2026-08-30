"""§11.2 — SOURCE UNIQUE des frais taker par venue. Aucun hardcode concurrent dans le cross-venue.

Les modules cross-venue portaient chacun leur propre défaut de frais (3.5, 4.5, 6.0…), qui pouvaient
diverger — donc un PnL net incohérent selon le module. Ici UNE seule autorité, surchargée par
l'environnement `HYPERSMART_FEE_<VENUE>_BPS`. Les défauts sont conservateurs et à caler sur le tier
RÉEL du compte ; l'important est qu'il n'existe qu'une source. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
import os

from hl_observer.economics.assumptions import (
    AssumptionClassification,
    EconomicAssumption,
    EconomicConfigError,
    EconomicRunMode,
    is_certifiable_mode,
    make_assumption,
)

#: Défauts taker (bps). À ajuster au tier réel via env ; NE PAS redéfinir ailleurs.
DEFAUTS_TAKER_BPS: dict[str, float] = {
    "HYPERLIQUID": 4.5,
    "BINANCE": 4.5,
}

_ALIAS = {
    "HL": "HYPERLIQUID", "HYPERLIQUID": "HYPERLIQUID", "HYPER": "HYPERLIQUID",
    "BIN": "BINANCE", "BINANCE": "BINANCE",
}

_SOURCE_REF = {
    "HYPERLIQUID": (
        "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees"
        "#perps-tier-0-read-2026-07-13"
    ),
    "BINANCE": "project:src/hl_observer/config/frais_venues.py#DEFAUTS_TAKER_BPS",
}


def _fallback_assumption(
    *,
    venue: str,
    value: float,
    reason: str,
    certification_eligible: bool,
    source_ref: str,
) -> EconomicAssumption:
    return make_assumption(
        assumption_id=f"fee.taker.{venue.lower()}.bps",
        name=f"Frais taker {venue} par fill",
        value=float(value),
        unit="bps_per_fill",
        family_scope=("COPY_VAULT", "LEAD_LAG", "CROSS_VENUE"),
        classification=AssumptionClassification.CONSERVATIVE_DEFAULT,
        source_ref=source_ref,
        fallback_reason=reason,
        certification_eligible=certification_eligible,
        owner="HyperSmart/economic-config",
    )


def hypothese_frais_taker(
    venue: object,
    *,
    defaut: float | None = None,
    mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
    fallback: EconomicAssumption | None = None,
) -> EconomicAssumption:
    """Resolve a taker fee together with its certification provenance.

    Exploratory callers retain the historical conservative fallback. Certifiable,
    OOS, forward and promotion callers fail closed on an explicit malformed
    override or on an unknown venue without a predeclared typed fallback.
    """

    certifiable = is_certifiable_mode(mode)
    v = _ALIAS.get(str(venue or "").strip().upper())
    if v is None:
        if fallback is not None:
            if (
                fallback.classification is not AssumptionClassification.CONSERVATIVE_DEFAULT
                or fallback.unit != "bps_per_fill"
                or not fallback.certification_eligible
            ):
                raise EconomicConfigError(
                    "fallback de frais inconnu non predeclare ou non certifiable",
                    field=str(venue),
                )
            return fallback
        if certifiable:
            raise EconomicConfigError(
                f"venue de frais inconnue sans fallback type: {venue!r}",
                field=str(venue),
            )
        value = float(defaut) if defaut is not None else max(DEFAUTS_TAKER_BPS.values())
        return _fallback_assumption(
            venue="UNKNOWN",
            value=value,
            reason=f"UNKNOWN_VENUE:{venue!r}",
            certification_eligible=False,
            source_ref="exploratory:unknown-venue-conservative-maximum",
        )

    env_key = f"HYPERSMART_FEE_{v}_BPS"
    raw = os.environ.get(env_key)
    if raw is not None:
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            if certifiable:
                raise EconomicConfigError(
                    f"{env_key} invalide: {raw!r}",
                    field=env_key,
                ) from exc
            return _fallback_assumption(
                venue=v,
                value=DEFAUTS_TAKER_BPS[v],
                reason=f"INVALID_EXPLICIT_OVERRIDE:{env_key}",
                certification_eligible=False,
                source_ref=_SOURCE_REF[v],
            )
        if not math.isfinite(value) or value < 0.0:
            if certifiable:
                raise EconomicConfigError(
                    f"{env_key} doit etre un nombre fini positif ou nul",
                    field=env_key,
                )
            return _fallback_assumption(
                venue=v,
                value=DEFAUTS_TAKER_BPS[v],
                reason=f"INVALID_EXPLICIT_OVERRIDE:{env_key}",
                certification_eligible=False,
                source_ref=_SOURCE_REF[v],
            )
        return make_assumption(
            assumption_id=f"fee.taker.{v.lower()}.bps",
            name=f"Frais taker {v} par fill",
            value=value,
            unit="bps_per_fill",
            family_scope=("COPY_VAULT", "LEAD_LAG", "CROSS_VENUE"),
            classification=AssumptionClassification.CONFIGURED,
            source_ref=f"env:{env_key}",
            effective_from="run_bootstrap",
            owner="HyperSmart/operator-config",
            certification_eligible=True,
        )

    return _fallback_assumption(
        venue=v,
        value=DEFAUTS_TAKER_BPS[v],
        reason="NO_EXPLICIT_OVERRIDE_USE_PREDECLARED_DEFAULT",
        certification_eligible=True,
        source_ref=_SOURCE_REF[v],
    )


def frais_taker_bps(
    venue: object,
    *,
    defaut: float | None = None,
    mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
    fallback: EconomicAssumption | None = None,
) -> float:
    """Frais taker (bps) de la venue, depuis l'unique source. Env `HYPERSMART_FEE_<VENUE>_BPS` prioritaire."""
    return float(
        hypothese_frais_taker(
            venue,
            defaut=defaut,
            mode=mode,
            fallback=fallback,
        ).value
    )


__all__ = ["DEFAUTS_TAKER_BPS", "frais_taker_bps", "hypothese_frais_taker"]
